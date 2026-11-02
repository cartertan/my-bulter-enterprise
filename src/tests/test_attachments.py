"""Test mission attachment isolation, image boundaries and Office edit fidelity.

Inputs: Synthetic files and isolated clients. Outputs: assertions, no external
API calls or private data. Author: Carter Tan.
"""
import base64
import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from docx import Document
from PIL import Image
from pptx import Presentation
from fastapi.testclient import TestClient

from src.app import create_app
from src.attachments import parse, template_output, edited_output, office_paragraphs
from src.providers import request_spec


def office(kind: str, text: str) -> bytes:
    """Build a real Office fixture with styled source text."""
    output = io.BytesIO()
    if kind == 'docx':
        document = Document()
        document.add_paragraph(text)
    else:
        document = Presentation()
        slide = document.slides.add_slide(document.slide_layouts[6])
        from pptx.util import Inches
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(4)).text = text
    document.save(output)
    return output.getvalue()


def completed(output: str) -> dict:
    """Provide the minimal completed mission shape."""
    return {'status': 'completed', 'prompt': 'Synthetic request', 'steps': [{'output': output}]}


@pytest.mark.parametrize('kind', ['docx', 'pptx'])
def test_office_edit_and_template_preserve_parts(kind: str) -> None:
    """Unchanged package parts retain their exact bytes; replacement is grounded."""
    source = office(kind, 'Original example')
    result = edited_output(source, 'sample.' + kind, completed(json.dumps({'replacements': [{'old': 'Original example', 'new': 'New approved wording'}]})))
    assert office_paragraphs(result, 'result.' + kind) == ['New approved wording']
    with zipfile.ZipFile(io.BytesIO(source)) as old, zipfile.ZipFile(io.BytesIO(result)) as new:
        for name in old.namelist():
            if name != 'word/document.xml' and not name.startswith('ppt/slides/slide'):
                assert old.read(name) == new.read(name)
    template = office(kind, '{{RESPONSE}}')
    assert 'Completed text' in office_paragraphs(template_output(template, 'sample.' + kind, completed('Completed text')), 'result.' + kind)
    with pytest.raises(ValueError, match='invalid or ambiguous'):
        edited_output(source, 'sample.' + kind, completed('{"replacements":[{"old":"absent","new":"bad"}]}'))


def test_photo_normalized_and_limits() -> None:
    """Images are decoded, resized and re-encoded, with malformed inputs refused."""
    output = io.BytesIO()
    Image.new('RGB', (2000, 1000), 'red').save(output, 'PNG')
    parsed = parse(output.getvalue(), 'photo.png')
    assert parsed['width'] == 1600 and parsed['height'] == 800
    assert base64.b64decode(parsed['image']).startswith(b'\xff\xd8')
    assert request_spec('ollama', 'vision', 'system', [{'role': 'user', 'content': 'Read photo', 'images': [parsed['image']]}])[2]['messages'][1]['images']
    with pytest.raises(ValueError):
        parse(b'x' * 12001, 'long.txt')
    with pytest.raises(Exception):
        parse(b'not an image', 'fake.png')


def test_attachment_mission_flow(tmp_path: Path, monkeypatch) -> None:
    """Selected references reach inference, persist on the mission, never become memory."""
    observed = []
    async def fake_generate(provider, model, system, messages, **kwargs):
        observed.append(messages)
        yield 'Synthetic analysis'
    monkeypatch.setattr('src.app.generate', fake_generate)
    app = create_app(tmp_path / 'test.sqlite3')
    with TestClient(app) as client:
        assert client.post('/api/attachments?filename=test.txt', content=b'test').status_code == 403
        client.headers['x-bulter-token'] = app.state.csrf
        result = client.post('/api/attachments?filename=sample.txt', content=b'Evidence uniquely attached to this mission')
        assert result.status_code == 200, result.text
        attachment = result.json()
        assert 'raw' not in attachment and 'image' not in attachment
        assert client.post('/api/attachments?filename=../bad.txt', content=b'x').status_code == 400
        bot = client.post('/api/bulters', json={'name':'Test', 'role':'Analysis', 'instructions':'Use evidence', 'provider':'ollama','model':'test','shared_memory':False}).json()
        response = client.post('/api/missions', json={'prompt':'Review the evidence', 'bulter_ids':[bot['id']], 'attachment_ids':[attachment['id']]})
        assert response.status_code == 200, response.text
        for _ in range(100):
            mission = app.state.store.get('mission', response.json()['id'])
            if mission['status'] not in {'queued', 'running'}:
                break
            time.sleep(.01)
        assert mission['status'] == 'completed'
        assert 'Evidence uniquely attached' in observed[0][0]['content']
        assert not app.state.store.all('memory')
        assert client.post('/api/missions', json={'prompt':'Review', 'bulter_ids':[bot['id']], 'attachment_ids':['missing']}).status_code == 404
        assert client.post('/api/missions', json={'prompt':'Review', 'bulter_ids':[bot['id']], 'attachment_mode':'edit'}).status_code == 400
        cloud_bot = client.post('/api/bulters', json={'name':'Cloud', 'role':'Analysis', 'instructions':'Use evidence', 'provider':'openai','model':'test','shared_memory':False}).json()
        response = client.post('/api/missions', json={'prompt':'Review', 'bulter_ids':[cloud_bot['id']], 'attachment_ids':[attachment['id']], 'cloud_consent':True})
        assert response.status_code == 400 and 'attachments' in response.json()['detail']


def test_photo_delivery_and_template_export(tmp_path: Path, monkeypatch) -> None:
    """Verify photo bytes reach inference and validated edits reach the download."""
    observed = []
    async def fake_vision(bots):
        return None
    async def fake_generate(provider, model, system, messages, **kwargs):
        observed.append(messages)
        yield json.dumps({'replacements':[{'old':'Original example','new':'Reviewed replacement'}]})
    monkeypatch.setattr('src.app.require_vision', fake_vision)
    monkeypatch.setattr('src.app.generate', fake_generate)
    app = create_app(tmp_path / 'test.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        output = io.BytesIO()
        Image.new('RGB', (64,64), 'blue').save(output, 'PNG')
        photo = client.post('/api/attachments?filename=photo.png', content=output.getvalue()).json()
        template = client.post('/api/attachments?filename=sample.docx', content=office('docx', 'Original example')).json()
        assert client.get(f"/api/attachments/{photo['id']}/preview").content.startswith(b'\xff\xd8')
        bot = client.post('/api/bulters', json={'name':'Vision', 'role':'Analysis','instructions':'Use evidence','provider':'ollama','model':'vision','shared_memory':False}).json()
        result = client.post('/api/missions', json={'prompt':'Replace example wording', 'bulter_ids':[bot['id']], 'attachment_ids':[photo['id'],template['id']], 'attachment_mode':'edit', 'template_id':template['id']})
        assert result.status_code == 200, result.text
        for _ in range(100):
            mission = app.state.store.get('mission', result.json()['id'])
            if mission['status'] not in {'running','queued'}:
                break
            time.sleep(.01)
        assert observed[0][0]['images']
        assert 'editable_paragraphs' in observed[0][0]['content']
        response = client.get(f"/api/missions/{mission['id']}/export/docx?use_template=true")
        assert response.status_code == 200, response.text
        assert office_paragraphs(response.content, 'edited.docx') == ['Reviewed replacement']


def test_vision_capability_fails_closed(monkeypatch) -> None:
    """A text-only model is rejected before an image inference call."""
    import asyncio
    import httpx
    from fastapi import HTTPException
    from src.attachment_routes import require_vision
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'capabilities':['completion']}))
    monkeypatch.setattr('src.attachment_routes.httpx.AsyncClient', lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(HTTPException, match='does not support vision'):
        asyncio.run(require_vision([{'provider':'ollama','model':'text-only'}]))
    with pytest.raises(HTTPException, match='Ollama'):
        asyncio.run(require_vision([{'provider':'openai','model':'cloud'}]))


def linked_office(kind: str, text: str, target: str, relationship_type: str = 'hyperlink', mode: str = 'External') -> bytes:
    """Create a real linked run, then vary only its relationship for security tests."""
    from lxml import etree as ET
    source = io.BytesIO()
    if kind == 'docx':
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.opc.constants import RELATIONSHIP_TYPE
        document = Document()
        paragraph = document.add_paragraph()
        run = paragraph.add_run(text)
        link = OxmlElement('w:hyperlink')
        link.set(qn('r:id'), document.part.relate_to(target, RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
        link.append(run._r)
        paragraph._p.append(link)
    else:
        from pptx.util import Inches
        document = Presentation()
        slide = document.slides.add_slide(document.slide_layouts[6])
        run = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(4)).text_frame.paragraphs[0].add_run()
        run.text = text
        run.hyperlink.address = target
    document.save(source)
    output = io.BytesIO()
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(output, 'w') as new:
        for item in old.infolist():
            content = old.read(item.filename)
            if item.filename.endswith('.rels'):
                root = ET.fromstring(content)
                for node in root:
                    if node.get('Type', '').endswith('/hyperlink'):
                        node.set('Type', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/' + relationship_type)
                        node.set('TargetMode', mode)
                content = ET.tostring(root)
            new.writestr(item, content)
    return output.getvalue()


@pytest.mark.parametrize('kind', ['docx', 'pptx'])
@pytest.mark.parametrize('operation', ['edit', 'placeholder'])
def test_https_citations_preserve_relationship_and_unchanged_parts(kind: str, operation: str) -> None:
    """A real citation survives preflight and export without touching other parts."""
    original = 'Original wording' if operation == 'edit' else '{{RESPONSE}}'
    source = linked_office(kind, original, 'https://example.com/research?q=wallet#citations')
    assert office_paragraphs(source, 'source.' + kind) == [original]
    if operation == 'edit':
        result = edited_output(source, 'source.' + kind, completed(json.dumps({'replacements': [{'old': original, 'new': 'New wording'}]})))
    else:
        result = template_output(source, 'source.' + kind, completed('New wording'))
    assert office_paragraphs(result, 'result.' + kind) == ['New wording']
    changed_part = 'word/document.xml' if kind == 'docx' else 'ppt/slides/slide1.xml'
    with zipfile.ZipFile(io.BytesIO(source)) as old, zipfile.ZipFile(io.BytesIO(result)) as new:
        assert old.namelist() == new.namelist()
        assert all(old.read(name) == new.read(name) for name in old.namelist() if name != changed_part)
    # Reopen with the native document library as a structural compatibility check.
    (Document if kind == 'docx' else Presentation)(io.BytesIO(result))


@pytest.mark.parametrize('target', [
    'http://example.com/citation', 'file:///tmp/example', 'javascript:alert(1)',
    '//example.com/citation', 'https://user:password@example.com',
    'https://127.0.0.1/citation', 'https://[::1]/citation', 'https://localhost/citation',
    'https://service.local/citation', 'https://example.com:8443/citation',
    'https://example.com:bad/citation', 'https://example.com/%0aevil',
    'https://example.com/%ZZ', 'https://example.com\\evil', 'https://bad host.com',
    'https://example.com./', 'https://example..com/', 'https://2130706433/',
])
def test_unsafe_citation_targets_rejected(target: str) -> None:
    """No script/file/local/ambiguous targets receive the HTTPS exception."""
    from src.attachments import citation_target_allowed
    assert not citation_target_allowed(target)
    source = linked_office('pptx', '{{RESPONSE}}', target)
    with pytest.raises(ValueError):
        office_paragraphs(source, 'source.pptx')
    with pytest.raises(ValueError):
        template_output(source, 'source.pptx', completed('New wording'))


@pytest.mark.parametrize('kind', ['docx', 'pptx'])
@pytest.mark.parametrize('relationship_type,mode', [('attachedTemplate', 'External'), ('oleObject', 'External'),
    ('image', 'External'), ('hyperlink', 'external'), ('hyperlink', 'Internal')])
def test_external_objects_and_disguised_modes_rejected(kind: str, relationship_type: str, mode: str) -> None:
    """The exception is restricted to hyperlink type and exact external mode."""
    source = linked_office(kind, 'Original wording', 'https://example.com/citation', relationship_type, mode)
    with pytest.raises(ValueError):
        office_paragraphs(source, 'source.' + kind)
    with pytest.raises(ValueError):
        edited_output(source, 'source.' + kind, completed(json.dumps({'replacements': [{'old': 'Original wording', 'new': 'New wording'}]})))


@pytest.mark.parametrize('name', ['ppt/embeddings/object.bin', 'word/activeX/control.xml'])
def test_active_parts_still_block_preflight(name: str) -> None:
    """A valid citation does not weaken the embedded-object prohibition."""
    source = linked_office('pptx', '{{RESPONSE}}', 'https://example.com/citation')
    output = io.BytesIO(source)
    with zipfile.ZipFile(output, 'a') as archive:
        archive.writestr(name, b'synthetic')
    with pytest.raises(ValueError, match='active content'):
        office_paragraphs(output.getvalue(), 'source.pptx')


@pytest.mark.parametrize('content', [
    b'<Relationships',
    b'<Relationships xmlns="urn:wrong"/>',
    b'<!DOCTYPE Relationships [<!ENTITY x "https://example.com">]><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
    b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="a" Target="a" Type="t"/><Relationship Id="a" Target="b" Type="t"/></Relationships>',
])
def test_malformed_relationships_fail_closed(content: bytes) -> None:
    """Malformed roots, duplicate IDs and entity declarations are not preserved."""
    from src.attachments import validate_office_part
    with pytest.raises(ValueError):
        validate_office_part('ppt/slides/_rels/slide1.xml.rels', content)


def test_unsafe_template_rejected_before_model_call(tmp_path: Path, monkeypatch) -> None:
    """Office edit preflight checks relationship safety before inference."""
    calls = []

    async def stream(*args, **kwargs):
        """Any model invocation here is a regression."""
        calls.append(True)
        yield 'Unexpected'

    monkeypatch.setattr('src.app.generate', stream)
    app = create_app(tmp_path / 'test.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bot = client.post('/api/bulters', json={'name': 'Test', 'role': 'Edit', 'provider': 'ollama', 'model': 'test'}).json()
        source = linked_office('pptx', 'Original wording', 'https://example.com/payload', 'oleObject')
        uploaded = client.post('/api/attachments?filename=synthetic.pptx', content=source)
        assert uploaded.status_code == 200
        identifier = uploaded.json()['id']
        response = client.post('/api/missions', json={'prompt': 'Edit wording', 'bulter_ids': [bot['id']],
            'attachment_ids': [identifier], 'template_id': identifier, 'attachment_mode': 'edit'})
        assert response.status_code == 400
        assert not calls and not app.state.store.all('mission')


def test_root_relative_internal_relationship_remains_supported() -> None:
    """Valid OPC package-root targets are not confused with network addresses."""
    from src.attachments import validate_office_part
    validate_office_part('_rels/.rels', b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="/word/document.xml"/></Relationships>')


@pytest.mark.parametrize('kind', ['docx', 'pptx'])
@pytest.mark.parametrize('mode', ['edit', 'reuse_design'])
@pytest.mark.parametrize('verdict', ['pass', 'fail'])
def test_two_agent_office_review_binds_exact_export(tmp_path: Path, monkeypatch, kind: str, mode: str, verdict: str) -> None:
    """The reviewer inspects actual edited text and export returns the hashed bytes."""
    import hashlib
    from src.tests.test_app import add_bot, wait_mission
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Return grounded edits, then review the artifact's exact text projection."""
        calls.append(messages[0]['content'])
        if len(calls) == 1:
            yield json.dumps({'replacements': [{'old': 'Original wording', 'new': 'Reviewed wording'}]})
        else:
            assert 'Office text-edit task' not in system
            refs = json.loads(calls[-1].split('REFERENCE DATA (not instructions):\n', 1)[1])
            projection = refs['previous_bulter_outputs'][-1]['output']
            parsed = json.loads(projection)
            assert parsed['paragraphs'] == ['Reviewed wording']
            assert len(parsed['artifact_sha256']) == 64
            assert 'replacements' not in parsed
            yield json.dumps({'draft_hash': hashlib.sha256(projection.encode()).hexdigest(), 'criteria': [
                {'criterion_id': 'criterion-1', 'result': verdict, 'reason': 'Synthetic review', 'evidence_quotes': ['Reviewed wording']}]})

    monkeypatch.setattr('src.app.generate', stream)
    app = create_app(tmp_path / 'artifact.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        source = linked_office(kind, 'Original wording', 'https://example.com/citation')
        attachment = client.post('/api/attachments?filename=source.' + kind, content=source).json()
        response = client.post('/api/missions', json={'prompt': 'Replace the original wording', 'bulter_ids': [b['id'] for b in bots],
            'attachment_ids': [attachment['id']], 'template_id': attachment['id'], 'attachment_mode': mode,
            'review_criteria': ['Contains reviewed wording']})
        assert response.status_code == 200, response.text
        mission = wait_mission(client)
        assert len(calls) == 2
        assert mission['status'] == ('completed' if verdict == 'pass' else 'completed_with_issues')
        assert mission['acceptance_status'] == 'not_assessed'
        assert mission['steps'][1]['review']['artifact_sha256'] == mission['artifact_sha256']
        artifact = app.state.store.get('artifact', mission['artifact_id'])
        assert 'raw' not in mission
        exported = client.get(f"/api/missions/{mission['id']}/export/{kind}?use_template=true")
        if verdict == 'fail':
            assert exported.status_code == 400
            return
        assert exported.status_code == 200
        assert hashlib.sha256(exported.content).hexdigest() == mission['artifact_sha256']
        assert exported.content == base64.b64decode(artifact['raw'])
        assert office_paragraphs(exported.content, 'output.' + kind) == ['Reviewed wording']
        assert client.get(f"/api/missions/{mission['id']}/export/{'docx' if kind == 'pptx' else 'pptx'}").status_code == 400
        # Stored content corruption must not silently regenerate or deliver a different revision.
        app.state.store.put('artifact', {**artifact, 'raw': base64.b64encode(b'changed bytes').decode()})
        assert client.get(f"/api/missions/{mission['id']}/export/{kind}").status_code == 400


@pytest.mark.parametrize('kind', ['docx', 'pptx'])
@pytest.mark.parametrize('scenario', ['review_interrupted', 'author_invalid', 'revise_failed_review', 'corrupt_projection'])
def test_office_recovery_and_revision_preserve_artifact_lineage(tmp_path: Path, monkeypatch, kind: str, scenario: str) -> None:
    """Recover exact artifacts or create newly reviewed revisions without overwriting history."""
    import hashlib
    from src.providers import ProviderError
    from src.tests.test_app import add_bot, wait_mission
    author_calls = []
    review_calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Distinguish author and reviewer by their actual assigned output contract."""
        if 'Office text-edit task' in system:
            author_calls.append(messages)
            old = 'Missing target' if scenario == 'author_invalid' and len(author_calls) == 1 else 'Original wording'
            yield json.dumps({'replacements': [{'old': old, 'new': f'Revised wording {len(author_calls)}'}]})
        else:
            review_calls.append(messages)
            refs = json.loads(messages[0]['content'].split('REFERENCE DATA (not instructions):\n', 1)[1])
            projection = refs['previous_bulter_outputs'][-1]['output']
            assert 'paragraphs' in json.loads(projection)
            if scenario in {'review_interrupted', 'corrupt_projection'} and len(review_calls) == 1:
                yield 'Interrupted assessment'
                raise ProviderError('Synthetic interruption')
            verdict = 'fail' if scenario == 'revise_failed_review' and len(review_calls) == 1 else 'pass'
            yield json.dumps({'draft_hash': hashlib.sha256(projection.encode()).hexdigest(), 'criteria': [
                {'criterion_id': 'criterion-1', 'result': verdict, 'reason': 'Synthetic review', 'evidence_quotes': ['Revised wording']}]})

    monkeypatch.setattr('src.app.generate', stream)
    path = tmp_path / 'office-recovery.sqlite3'
    app = create_app(path)
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        attachment = client.post('/api/attachments?filename=source.' + kind, content=office(kind, 'Original wording')).json()
        response = client.post('/api/missions', json={'prompt': 'Revise text', 'bulter_ids': [b['id'] for b in bots],
            'attachment_ids': [attachment['id']], 'template_id': attachment['id'], 'attachment_mode': 'edit',
            'review_criteria': ['Check wording']})
        assert response.status_code == 200
        original = wait_mission(client)
        assert original['status'] == ('completed_with_issues' if scenario == 'revise_failed_review' else 'failed')
        if scenario == 'author_invalid':
            assert original['steps'][0]['status'] == 'failed'
            assert 'artifact_id' not in original
        if scenario == 'corrupt_projection':
            artifact = app.state.store.get('artifact', original['artifact_id'])
            app.state.store.put('artifact', {**artifact, 'review_text': 'Forged review projection'})
    # Restart must not repeat completed author inference or trust corrupted projection text.
    fresh = create_app(path)
    with TestClient(fresh) as client:
        client.headers['x-bulter-token'] = fresh.state.csrf
        action = 'revise' if scenario == 'revise_failed_review' else 'resume'
        response = client.post(f"/api/missions/{original['id']}/{action}", json={})
        if scenario == 'corrupt_projection':
            assert response.status_code == 409
            assert len(author_calls) == len(review_calls) == 1
            return
        assert response.status_code == 200, response.text
        child = wait_mission(client)
        assert child['status'] == 'completed'
        assert child['acceptance_status'] == 'not_assessed'
        assert child['attempt_kind'] == ('revision' if scenario == 'revise_failed_review' else 'recovery')
        assert fresh.state.store.get('mission', original['id']) == original
        exported = client.get(f"/api/missions/{child['id']}/export/{kind}")
        assert exported.status_code == 200
        assert hashlib.sha256(exported.content).hexdigest() == child['artifact_sha256']
        if scenario == 'review_interrupted':
            assert len(author_calls) == 1 and len(review_calls) == 2
            assert child['artifact_sha256'] == original['artifact_sha256']
            assert child['artifact_id'] != original['artifact_id']
        else:
            assert len(author_calls) == 2
            assert office_paragraphs(exported.content, 'result.' + kind) == ['Revised wording 2']
            if scenario == 'revise_failed_review':
                assert child['artifact_sha256'] != original['artifact_sha256']
                assert child['steps'][1]['review']['artifact_sha256'] == child['artifact_sha256']


@pytest.mark.parametrize("use_template", [False, True])
@pytest.mark.parametrize("use_picture", [False, True, "omitted"])
def test_composed_presentation_contains_editable_diagram_and_notes(tmp_path: Path, monkeypatch, use_template: bool, use_picture: bool | str) -> None:
    """The app produces and reviews actual slide bytes, not a prose description."""
    import hashlib
    from pptx.enum.shapes import MSO_SHAPE
    from src.tests.test_app import add_bot, wait_mission
    manifest = {'slides': [{'slide_id': 'slide-1', 'title': 'Wallet issuance', 'body': 'The holder consents before issuance.',
        'speaker_notes': 'Explain identity proofing and explicit consent.', 'duration_seconds': 120,
        'flow_steps': ['Prove identity', 'Holder consents', 'Receive credential']}], 'discussion_seconds': 60}
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Generate a timed manifest and assess the resulting artifact text."""
        calls.append(messages)
        if len(calls) == 1:
            assert 'flow_steps' in messages[0]['content']
            schema = kwargs['options']['response_schema']
            assert schema['$defs']['TimedSlide']['properties']['duration_seconds']['minimum'] == 1
            assert schema['properties']['discussion_seconds']['minimum'] == 0
            assert schema['additionalProperties'] is False
            if use_picture == 'omitted':
                manifest['slides'] = manifest['slides'][:1]
            yield json.dumps(manifest)
        else:
            assert hashlib.sha256(json.dumps(manifest).encode()).hexdigest() not in messages[0]['content']
            assert 'DETERMINISTIC TIMING CHECK' in messages[0]['content']
            refs = json.loads(messages[0]['content'].split('REFERENCE DATA (not instructions):\n', 1)[1])
            projection = refs['previous_bulter_outputs'][-1]['output']
            assert 'Holder consents' in projection
            yield json.dumps({'draft_hash': hashlib.sha256(projection.encode()).hexdigest(), 'criteria': [
                {'criterion_id': 'criterion-1', 'result': 'pass', 'reason': 'The flow includes consent', 'evidence_quotes': ['Holder consents']}]})

    async def fake_vision(bots):
        return None
    monkeypatch.setattr('src.app.require_vision', fake_vision)
    monkeypatch.setattr('src.app.generate', stream)
    app = create_app(tmp_path / 'composed.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        template_options = {}
        if use_template:
            uploaded = client.post('/api/attachments?filename=design.pptx', content=office('pptx', 'Obsolete sample')).json()
            template_options = {'attachment_ids': [uploaded['id']], 'template_id': uploaded['id']}
        if use_picture:
            photo = io.BytesIO()
            Image.new('RGB', (400, 200), 'blue').save(photo, format='PNG')
            uploaded_photo = client.post('/api/attachments?filename=synthetic.png', content=photo.getvalue()).json()
            template_options.setdefault('attachment_ids', []).append(uploaded_photo['id'])
            template_options['require_picture'] = True
            manifest['slides'].append({'slide_id': 'slide-2', 'title': 'Illustration', 'body': 'Synthetic test image',
                'speaker_notes': 'Illustration only', 'duration_seconds': 60, 'image_id': uploaded_photo['id'],
                'image_caption': 'Synthetic illustration'})
        response = client.post('/api/missions', json={**template_options, 'prompt': 'Explain wallet issuance with a flow diagram',
            'bulter_ids': [b['id'] for b in bots], 'duration_budget_seconds': 1800,
            'review_criteria': ['Include holder consent'], 'compose_presentation': True})
        assert response.status_code == 200
        mission = wait_mission(client)
        if use_picture == 'omitted':
            assert mission['status'] == 'failed' and len(calls) == 1
            assert not mission.get('artifact_id')
            return
        assert mission['status'] == 'completed' and len(calls) == 2
        assert mission['acceptance_status'] == 'not_assessed'
        exported = client.get(f"/api/missions/{mission['id']}/export/pptx")
        assert exported.status_code == 200
        assert hashlib.sha256(exported.content).hexdigest() == mission['artifact_sha256']
        deck = Presentation(io.BytesIO(exported.content))
        assert len(deck.slides) == (2 if use_picture else 1)
        if use_picture:
            pictures = [shape for shape in deck.slides[1].shapes if shape.shape_type == 13]
            assert len(pictures) == 1
            picture = pictures[0]
            assert picture.width / picture.height == pytest.approx(2, abs=.00001)
            normalized = base64.b64decode(app.state.store.get('attachment', uploaded_photo['id'])['image'])
            assert picture.image.blob == normalized
            digest = hashlib.sha256(normalized).hexdigest()
            assert digest in deck.slides[1].notes_slide.notes_text_frame.text
            assert 'Synthetic illustration' in '\n'.join(shape.text for shape in deck.slides[1].shapes if shape.has_text_frame)
            artifact = app.state.store.get('artifact', mission['artifact_id'])
            assert artifact['image_assets'][0]['sha256'] == digest
        slide = deck.slides[0]
        types = [shape.auto_shape_type for shape in slide.shapes if shape.shape_type == 1]
        assert types.count(MSO_SHAPE.ROUNDED_RECTANGLE) == 3
        assert types.count(MSO_SHAPE.DOWN_ARROW) == 2
        assert 'Explain identity proofing' in slide.notes_slide.notes_text_frame.text
        assert 'Presentation discussion: 60 seconds' in slide.notes_slide.notes_text_frame.text
        assert all(shape.left >= 0 and shape.top >= 0 and shape.left + shape.width <= deck.slide_width
                   and shape.top + shape.height <= deck.slide_height for shape in slide.shapes)


@pytest.mark.parametrize('problem', ['long_title', 'long_body', 'long_flow', 'placeholder', 'unknown_source'])
def test_composer_rejects_content_it_cannot_place(problem: str) -> None:
    """Layout budgets reject content instead of silently deleting or shrinking it."""
    from src.presentation_builder import compose_presentation
    slide = {'slide_id': 'slide-1', 'title': 'Wallet flow', 'body': 'Consent precedes issuance',
             'speaker_notes': 'Explain consent', 'duration_seconds': 60, 'flow_steps': ['Consent', 'Issue']}
    if problem == 'long_title':
        slide['title'] = 'x' * 91
    elif problem == 'long_body':
        slide['body'] = 'x' * 421
    elif problem == 'long_flow':
        slide['flow_steps'] = ['x' * 51, 'Issue']
    elif problem == 'placeholder':
        slide['body'] = '{{RESPONSE}}'
    else:
        slide['claims'] = [{'text': 'Claim', 'evidence': [{'source_id': 'invented', 'quote': 'Quote'}]}]
    with pytest.raises(ValueError):
        compose_presentation({'slides': [slide], 'discussion_seconds': 0}, [])


def test_composition_reuses_theme_dimensions_and_replaces_sample_slides() -> None:
    """Custom theme bytes persist while generated text and diagram use its styling."""
    from lxml import etree as ET
    from src.presentation_builder import compose_presentation
    source = office('pptx', 'Obsolete sample wording')
    modified = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as old, zipfile.ZipFile(modified, 'w') as new:
        for item in old.infolist():
            content = old.read(item.filename)
            if item.filename == 'ppt/theme/theme1.xml':
                root = ET.fromstring(content)
                ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
                root.xpath('./a:themeElements/a:clrScheme/a:accent1/a:srgbClr', namespaces=ns)[0].set('val', 'AD2556')
                root.xpath('./a:themeElements/a:fontScheme/a:minorFont/a:latin', namespaces=ns)[0].set('typeface', 'Arial')
                content = ET.tostring(root)
            new.writestr(item, content)
    manifest = {'slides': [{'title': 'New presentation', 'body': 'New facts', 'speaker_notes': 'New notes',
        'duration_seconds': 120, 'flow_steps': ['Consent', 'Issue']}], 'discussion_seconds': 60}
    result = compose_presentation(manifest, [], modified.getvalue())
    original = Presentation(io.BytesIO(modified.getvalue()))
    deck = Presentation(io.BytesIO(result))
    assert (deck.slide_width, deck.slide_height) == (original.slide_width, original.slide_height)
    assert len(deck.slides) == 1
    assert 'Obsolete sample wording' not in '\n'.join(office_paragraphs(result, 'output.pptx'))
    nodes = [shape for shape in deck.slides[0].shapes if shape.has_text_frame and shape.text == 'Consent']
    assert str(nodes[0].fill.fore_color.rgb) == 'AD2556'
    assert nodes[0].text_frame.paragraphs[0].font.name == 'Arial'
    with zipfile.ZipFile(io.BytesIO(modified.getvalue())) as old, zipfile.ZipFile(io.BytesIO(result)) as new:
        assert old.read('ppt/theme/theme1.xml') == new.read('ppt/theme/theme1.xml')
        assert old.read('ppt/slideMasters/slideMaster1.xml') == new.read('ppt/slideMasters/slideMaster1.xml')


def test_unsupported_template_dimensions_fail_before_inference(tmp_path: Path, monkeypatch) -> None:
    """Portrait designs are explicitly unsupported instead of silently distorted."""
    from src.tests.test_app import add_bot
    from unittest.mock import Mock
    from pptx.util import Inches
    document = Presentation(io.BytesIO(office('pptx', 'Portrait sample')))
    document.slide_width, document.slide_height = Inches(7.5), Inches(10)
    source = io.BytesIO(); document.save(source)
    generate_mock = Mock()
    monkeypatch.setattr('src.app.generate', generate_mock)
    app = create_app(tmp_path / 'portrait.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        uploaded = client.post('/api/attachments?filename=portrait.pptx', content=source.getvalue()).json()
        response = client.post('/api/missions', json={'prompt': 'Compose', 'bulter_ids': [b['id'] for b in bots],
            'attachment_ids': [uploaded['id']], 'template_id': uploaded['id'], 'review_criteria': ['Check flow'],
            'duration_budget_seconds': 1800, 'compose_presentation': True})
        assert response.status_code == 400
        generate_mock.assert_not_called()


@pytest.mark.parametrize('problem', ['unknown', 'flow', 'caption', 'not_jpeg'])
def test_picture_composition_rejects_invalid_assets(problem: str) -> None:
    """Only selected normalized assets with a dedicated captioned layout are usable."""
    from src.presentation_builder import compose_presentation
    photo = io.BytesIO()
    Image.new('RGB', (40, 20), 'blue').save(photo, format='PNG' if problem == 'not_jpeg' else 'JPEG')
    slide = {'title': 'Picture', 'body': 'Illustration', 'speaker_notes': 'Test', 'duration_seconds': 60,
             'image_id': 'selected', 'image_caption': 'Synthetic image'}
    assets = {'selected': {'bytes': photo.getvalue(), 'filename': 'synthetic.jpg'}}
    if problem == 'unknown':
        slide['image_id'] = 'https://example.com/unselected.jpg'
    elif problem == 'flow':
        slide['flow_steps'] = ['Consent', 'Issue']
    elif problem == 'caption':
        slide['image_caption'] = ''
    with pytest.raises(ValueError):
        compose_presentation({'slides': [slide], 'discussion_seconds': 0}, [], images=assets)


def test_required_picture_missing_upload_rejected_before_inference(tmp_path: Path, monkeypatch) -> None:
    """A required picture cannot be promised without a selected uploaded asset."""
    from src.tests.test_app import add_bot
    from unittest.mock import Mock
    generate_mock = Mock()
    monkeypatch.setattr('src.app.generate', generate_mock)
    app = create_app(tmp_path / 'missing-picture.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        response = client.post('/api/missions', json={'prompt': 'Compose', 'bulter_ids': [b['id'] for b in bots],
            'review_criteria': ['Check flow'], 'duration_budget_seconds': 1800,
            'compose_presentation': True, 'require_picture': True})
        assert response.status_code == 400
        generate_mock.assert_not_called()


@pytest.mark.parametrize('field', ['title', 'body', 'flow', 'citation'])
@pytest.mark.parametrize('separator', ['\n', '\r\n', '\v'])
def test_composition_rejects_explicit_line_overflow(field: str, separator: str) -> None:
    """Short text can overflow vertically even within the character budget."""
    from src.presentation_builder import compose_presentation
    slide = {'title': 'Wallet', 'body': 'Consent', 'speaker_notes': 'Test', 'duration_seconds': 60,
             'flow_steps': ['Consent', 'Issue']}
    sources = []
    overflow = separator.join(['x'] * 20)
    if field in {'title', 'body'}:
        slide[field] = overflow
    elif field == 'flow':
        slide['flow_steps'] = [separator.join(['x'] * 3), 'Issue']
    else:
        sources = [{'source_id': 'source-1', 'title': overflow}]
        slide['claims'] = [{'evidence': [{'source_id': 'source-1', 'quote': 'Evidence'}]}]
    with pytest.raises(ValueError, match='Explicit text lines'):
        compose_presentation({'slides': [slide], 'discussion_seconds': 0}, sources)


def test_composition_four_citations_use_explicit_spacing() -> None:
    """All four allowed references fit the panel without inherited paragraph spacing."""
    from src.presentation_builder import compose_presentation
    sources = [{'source_id': f'source-{i}', 'title': f'Reference {i}'} for i in range(4)]
    slide = {'title': 'Wallet', 'body': 'Consent\r\nIssue', 'speaker_notes': 'Test', 'duration_seconds': 60,
             'flow_steps': ['Consent', 'Issue'], 'claims': [{'evidence': [
                 {'source_id': source['source_id'], 'quote': 'Evidence'} for source in sources]}]}
    deck = Presentation(io.BytesIO(compose_presentation({'slides': [slide], 'discussion_seconds': 0}, sources)))
    labels = [shape for shape in deck.slides[0].shapes if shape.has_text_frame and 'Reference 0' in shape.text]
    assert len(labels) == 1 and len(labels[0].text_frame.paragraphs) == 4
    for paragraph in labels[0].text_frame.paragraphs:
        assert paragraph.space_after.pt == 0 and paragraph.space_before.pt == 0
        assert paragraph.line_spacing == 1.2
    assert any(shape.has_text_frame and shape.text == 'Consent\nIssue' for shape in deck.slides[0].shapes)


@pytest.mark.parametrize('failure', ['none', 'hash', 'existing', 'renderer', 'page_count', 'image', 'corrupt_image', 'timeout'])
def test_render_evidence_requires_exact_artifact_and_all_pages(tmp_path: Path, monkeypatch, failure: str) -> None:
    """Partial/stale render evidence never produces a successful report."""
    import hashlib
    import subprocess
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from scripts.render_presentation import render_presentation
    source = tmp_path / 'source.pptx'
    source.write_bytes(office('pptx', 'Synthetic slide'))
    output = tmp_path / 'evidence'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if failure == 'existing':
        output.mkdir()
        (output / 'sentinel').write_text('preserve')
    monkeypatch.setattr('scripts.render_presentation.shutil.which', lambda name: None if failure == 'renderer' else name)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs['timeout'] == 120 and kwargs['check'] is True
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 120)
        if command[0] == 'soffice':
            (output / 'artifact.pdf').write_bytes(b'%PDF-synthetic fixture')
        elif failure != 'image':
            image = io.BytesIO()
            Image.new('RGB', (40, 20), 'blue').save(image, format='PNG')
            (output / 'slide-1.png').write_bytes(b'\x89PNG\r\n\x1a\ncorrupt' if failure == 'corrupt_image' else image.getvalue())
    monkeypatch.setattr('scripts.render_presentation.subprocess.run', run)
    document = MagicMock()
    document.__enter__.return_value = SimpleNamespace(pages=[] if failure == 'page_count' else [SimpleNamespace(extract_text=lambda: 'Synthetic slide')])
    monkeypatch.setattr('scripts.render_presentation.pdfplumber.open', lambda path: document)
    if failure != 'none':
        with pytest.raises((ValueError, OSError, subprocess.TimeoutExpired)):
            render_presentation(source, 'wrong' if failure == 'hash' else digest, output)
        assert not (output / 'render-report.json').exists()
        if failure in {'hash', 'existing', 'renderer'}:
            assert not calls
        if failure == 'existing':
            assert (output / 'sentinel').read_text() == 'preserve'
    else:
        report = render_presentation(source, digest, output)
        assert len(calls) == 2
        assert report['artifact_sha256'] == digest and report['slide_count'] == 1
        assert report['visual_inspection'] == 'pending' and report['user_acceptance'] == 'not_assessed'
        assert report['pages'][0]['sha256'] == hashlib.sha256((output / 'slide-1.png').read_bytes()).hexdigest()
        assert json.loads((output / 'render-report.json').read_text()) == report
        assert output.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('rendered,expected_state', [
    ('Consent before issuance', 'present'), ('Consent\nbefore  issuance', 'present'),
    ('Consent before', 'needs_review'), ('', 'needs_review')])
def test_render_text_presence_detects_missing_fragments(rendered: str, expected_state: str) -> None:
    """Extraction catches lost words, while harmless line wrapping is normalized."""
    from scripts.render_presentation import text_presence
    result = text_presence(['Consent before issuance'], rendered)
    assert result['state'] == expected_state
    assert bool(result['missing_fragments']) == (expected_state == 'needs_review')


def test_render_text_collection_includes_groups_tables_and_excludes_notes() -> None:
    """Text hidden in editable groups/tables must also be checked after rendering."""
    from scripts.render_presentation import slide_text_fragments, text_presence
    from pptx.util import Inches
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = 'Grouped text'
    table = slide.shapes.add_table(1, 1, 0, Inches(2), Inches(2), Inches(1)).table
    table.cell(0, 0).text = 'Table text'
    slide.notes_slide.notes_text_frame.text = 'Private speaker notes'
    assert slide_text_fragments(slide.shapes) == ['Grouped text', 'Table text']
    assert text_presence([], '')['state'] == 'not_assessed'


@pytest.mark.parametrize('kind', ['docx', 'pptx'])
@pytest.mark.parametrize('problem', ['none', 'hash', 'owner', 'format', 'projection', 'partial', 'running', 'missing'])
def test_unaccepted_draft_inspection_preserves_export_gates(tmp_path: Path, kind: str, problem: str) -> None:
    """Unresolved reviews can be inspected without exposing stale or partial artifacts."""
    import hashlib
    raw = office(kind, 'Unaccepted synthetic draft')
    digest = hashlib.sha256(raw).hexdigest()
    app = create_app(tmp_path / 'draft-inspection.sqlite3')
    mission = {'id': 'mission-1', 'status': 'completed_with_issues', 'artifact_id': 'artifact-1',
               'artifact_sha256': digest, 'artifact_format': kind, 'acceptance_status': 'not_assessed',
               'steps': [{'status': 'completed'}, {'status': 'completed', 'review': {'state': 'needs_revision'}}]}
    artifact = {'id': 'artifact-1', 'mission_id': mission['id'], 'format': kind,
                'sha256': digest, 'raw': base64.b64encode(raw).decode(),
                'review_text': json.dumps({'artifact_sha256': digest, 'paragraphs': office_paragraphs(raw, 'draft.' + kind)}, ensure_ascii=False)}
    if problem == 'hash':
        mission['artifact_sha256'] = 'changed'
    elif problem == 'owner':
        artifact['mission_id'] = 'another-mission'
    elif problem == 'format':
        mission['artifact_format'] = 'pptx' if kind == 'docx' else 'docx'
    elif problem == 'projection':
        artifact['review_text'] = 'changed'
    elif problem == 'partial':
        mission['steps'][0]['status'] = 'partial'
    elif problem == 'running':
        mission['status'] = 'running'
    app.state.store.put('mission', mission)
    if problem != 'missing':
        app.state.store.put('artifact', artifact)
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        if problem == 'running':
            # Set after startup so this tests an active run, not restart interruption.
            app.state.store.put('mission', mission)
        response = client.get('/api/missions/mission-1/artifact/draft')
        assert response.status_code == (200 if problem == 'none' else 409)
        if problem == 'none':
            assert response.content == raw
            assert response.headers['x-artifact-sha256'] == digest
            assert response.headers['cache-control'] == 'no-store'
            assert 'inspection-only' in response.headers['x-artifact-purpose']
            assert 'review-only-draft' in response.headers['content-disposition']
            assert app.state.store.get('mission', mission['id'])['acceptance_status'] == 'not_assessed'
        assert client.get('/api/missions/mission-1/export/' + kind).status_code == 400


@pytest.mark.parametrize('kind', ['docx', 'pptx'])
@pytest.mark.parametrize('author_status', ['completed', 'running', 'partial'])
def test_restart_keeps_complete_drafts_inspectable_without_acceptance(tmp_path: Path, kind: str, author_status: str) -> None:
    """A restart during review must not hide a complete artifact or expose partial work."""
    import hashlib
    raw = office(kind, 'Synthetic draft before restart')
    digest = hashlib.sha256(raw).hexdigest()
    database = tmp_path / 'restart-draft.sqlite3'
    original = create_app(database)
    mission = {'id': 'restart-mission', 'status': 'running', 'artifact_id': 'retained-artifact',
               'artifact_sha256': digest, 'artifact_format': kind, 'acceptance_status': 'not_assessed',
               'steps': [{'status': author_status}, {'status': 'running'}]}
    artifact = {'id': 'retained-artifact', 'mission_id': mission['id'], 'format': kind,
                'sha256': digest, 'raw': base64.b64encode(raw).decode(),
                'review_text': json.dumps({'artifact_sha256': digest,
                    'paragraphs': office_paragraphs(raw, 'draft.' + kind)}, ensure_ascii=False)}
    original.state.store.put('mission', mission)
    original.state.store.put('artifact', artifact)
    restarted = create_app(database)
    with TestClient(restarted) as client:
        client.headers['x-bulter-token'] = restarted.state.csrf
        restored = restarted.state.store.get('mission', mission['id'])
        assert restored['status'] == 'interrupted'
        response = client.get('/api/missions/restart-mission/artifact/draft')
        assert response.status_code == (200 if author_status == 'completed' else 409)
        if author_status == 'completed':
            assert response.content == raw and response.headers['x-artifact-sha256'] == digest
        assert client.get('/api/missions/restart-mission/export/' + kind).status_code == 400
        assert restarted.state.store.get('mission', mission['id']) == restored
        assert restored['acceptance_status'] == 'not_assessed'


def test_composition_reserves_template_footer_band() -> None:
    """Generated panels must leave retained bottom-of-slide branding unobstructed."""
    from copy import deepcopy
    from pptx.util import Inches
    from src.presentation_builder import compose_presentation
    template = Presentation()
    template.slide_width, template.slide_height = Inches(13.333), Inches(7.5)
    sample = template.slides.add_slide(template.slide_layouts[6])
    footer = sample.shapes.add_textbox(Inches(.2), Inches(7.02), Inches(2), Inches(.28))
    footer.text = 'Synthetic master footer'
    element = deepcopy(footer._element)
    element.xpath('.//p:cNvPr')[0].set('id', '10000')
    template.slide_master.shapes._spTree.insert_element_before(element, 'p:extLst')
    source = io.BytesIO(); template.save(source)
    photo = io.BytesIO(); Image.new('RGB', (400, 200), 'blue').save(photo, format='JPEG')
    sources = [{'source_id': str(i), 'title': f'Reference {i}'} for i in range(4)]
    common = {'body': 'Synthetic text', 'speaker_notes': 'Test only', 'duration_seconds': 60,
              'claims': [{'evidence': [{'source_id': s['source_id'], 'quote': 'Evidence'} for s in sources]}]}
    slides = [{**common, 'title': 'Flow', 'flow_steps': ['One', 'Two', 'Three', 'Four', 'Five']},
              {**common, 'title': 'Picture', 'image_id': 'photo', 'image_caption': 'Synthetic photo'}]
    result = compose_presentation({'slides': slides, 'discussion_seconds': 0}, sources, source.getvalue(),
                                 {'photo': {'bytes': photo.getvalue(), 'filename': 'synthetic.jpg'}})
    deck = Presentation(io.BytesIO(result))
    assert any(s.has_text_frame and s.text == 'Synthetic master footer' for s in deck.slide_master.shapes)
    for slide in deck.slides:
        assert all(shape.top + shape.height <= Inches(7.0) for shape in slide.shapes)
        citations = next(s for s in slide.shapes if s.has_text_frame and 'Reference 0' in s.text)
        timing = next(s for s in slide.shapes if s.has_text_frame and 'seconds' in s.text)
        assert citations.top + citations.height <= timing.top
        assert all(s.top + s.height <= citations.top for s in slide.shapes if s.top < citations.top)


@pytest.mark.parametrize('invalid_duration', [0, -1, True, '60'])
def test_author_schema_does_not_replace_timing_validation(tmp_path: Path, monkeypatch, invalid_duration) -> None:
    """A provider ignoring grammar still cannot create an invalid timed artifact."""
    from src.tests.test_app import add_bot, wait_mission
    calls = []
    async def stream(provider, model, system, messages, **kwargs):
        calls.append(kwargs['options'])
        assert 'response_schema' in kwargs['options']
        yield json.dumps({'slides': [{'slide_id': 's1', 'title': 'Flow', 'body': 'Consent',
            'speaker_notes': 'Synthetic only', 'duration_seconds': invalid_duration,
            'flow_steps': ['Consent', 'Issue']}], 'discussion_seconds': 0})
    monkeypatch.setattr('src.app.generate', stream)
    app = create_app(tmp_path / 'author-schema.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        response = client.post('/api/missions', json={'prompt': 'Synthetic test',
            'bulter_ids': [b['id'] for b in bots], 'review_criteria': ['Consent'],
            'duration_budget_seconds': 120, 'compose_presentation': True})
        assert response.status_code == 200
        mission = wait_mission(client)
        assert mission['status'] == 'failed' and len(calls) == 1
        assert 'Author outline is invalid' in mission['error']
        assert 'input_value' not in mission['error'] and 'pydantic.dev' not in mission['error']
        assert not mission.get('artifact_id')
        assert all('response_schema' not in b for b in mission['team'])
        assert client.get(f"/api/missions/{mission['id']}/export/pptx").status_code == 400
