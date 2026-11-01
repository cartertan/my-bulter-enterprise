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
