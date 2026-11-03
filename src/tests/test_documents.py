"""Exercise document boundaries with synthetic data only.

Inputs: Temporary files and test clients. Outputs: pytest assertions.
Assumptions: No live providers or personal vault. Author: Carter Tan.
"""
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from docx import Document
from pptx import Presentation

from src.app import create_app, eligible_memory
from src.documents import MAX_UPLOAD, chunks, export_mission, extract_text
from src.providers import request_spec


def mission() -> dict:
    """Provide a reproducible final response fixture."""
    return {"id": "demo", "status": "completed", "created": "2026-10-26", "prompt": "Review the synthetic architecture.",
            "steps": [{"name": "Atlas", "model": "synthetic", "output": "# Findings\nKeep source evidence.\n" + "Boundaries matter. " * 180}]}


def test_upload_review_approval_and_revocation(tmp_path: Path) -> None:
    """Drafts are inert; approval creates local-only Obsidian notes and is idempotent."""
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as client:
        assert client.post("/api/documents?filename=test.txt", content=b"test").status_code == 403
        client.headers["x-bulter-token"] = app.state.csrf
        uploaded = client.post("/api/documents?filename=evidence.txt", content=b"Synthetic PKI evidence. " * 200)
        assert uploaded.status_code == 200, uploaded.text
        document = uploaded.json()
        assert document["status"] == "draft" and len(document["chunks"]) > 1
        assert not app.state.store.all("memory")
        assert client.post("/api/documents?filename=evidence.txt", content=b"Synthetic PKI evidence. " * 200).json()["id"] == document["id"]
        for _ in range(2):
            assert client.post(f"/api/documents/{document['id']}/approve").status_code == 200
        notes = app.state.store.all("memory")
        assert len(notes) == len(document["chunks"])
        assert all(n["active"] and not n["cloud_allowed"] for n in notes)
        assert not eligible_memory(notes, {"id": "bot", "shared_memory": True}, True)
        note = next((tmp_path / "vault" / "50 Shared Knowledge").rglob("*.md"))
        note.write_text(note.read_text().replace("status: approved", "status: draft"))
        assert client.post("/api/obsidian/sync").json()["deactivated"] == 1


@pytest.mark.parametrize("name,data", [("../test.txt", b"test"), ("test.exe", b"MZ"), ("empty.txt", b""), ("fake.docx", b"not a zip"), ("binary.txt", b"\xff\xfe")])
def test_bad_uploads(tmp_path: Path, name: str, data: bytes) -> None:
    """Reject unsupported, malformed, empty and path-bearing uploads."""
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        assert client.post("/api/documents", params={"filename": name}, content=data).status_code == 400
        assert not app.state.store.all("memory")


def test_body_limits(tmp_path: Path) -> None:
    """A larger limit applies only to the authenticated binary upload route."""
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        assert client.post("/api/documents?filename=large.txt", content=b"a" * (MAX_UPLOAD + 1)).status_code == 413
        assert client.post("/api/memories", content=b"a" * 40001).status_code == 413


def test_exports_roundtrip_and_endpoint(tmp_path: Path) -> None:
    """Editable files retain the full response, and unfinished missions cannot export."""
    fixture = mission()
    docx = export_mission(fixture, "docx")
    pptx = export_mission(fixture, "pptx")
    assert "Keep source evidence." in extract_text(docx, "result.docx")
    doc = Document(io.BytesIO(docx))
    assert "Boundaries matter. " * 179 in "\n".join(p.text for p in doc.paragraphs)
    deck = Presentation(io.BytesIO(pptx))
    assert len(deck.slides) > 1
    text = " ".join(" ".join(slide.shapes[1].text.split()) for slide in deck.slides)
    assert text.count("Boundaries matter.") == 180
    app = create_app(tmp_path / "test.sqlite3")
    app.state.store.put("mission", fixture)
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        assert client.get("/api/missions/demo/export/docx").content.startswith(b"PK")
        assert client.get("/api/missions/demo/export/pptx").status_code == 200
        assert client.get("/api/missions/demo/export/html").status_code == 400
        assert client.get("/api/missions/missing/export/docx").status_code == 404
    with pytest.raises(ValueError):
        export_mission({**fixture, "status": "failed"}, "docx")


def test_extraction_tables_and_bomb_guard() -> None:
    """Tables are extracted; compressed oversized Office payloads are refused."""
    document = Document()
    document.add_paragraph("Heading")
    document.add_table(1, 2).cell(0, 0).text = "Evidence cell"
    stream = io.BytesIO()
    document.save(stream)
    assert "Evidence cell" in extract_text(stream.getvalue(), "table.docx")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.xml", b"a" * (41 * 1024 * 1024))
    with pytest.raises(ValueError, match="decompression"):
        extract_text(stream.getvalue(), "bomb.docx")


def test_chunking_and_inference_controls() -> None:
    """No text loss; settings reach Ollama without affecting paid provider requests."""
    text = "x" * 6001
    assert "".join(chunks(text)) == text
    body = request_spec("ollama", "qwen3.8:27b", "system", [],
                        {"output_tokens": 8192, "context_tokens": 32768, "thinking": "off"})[2]
    assert body["think"] is False and body["options"] == {"num_predict": 8192, "num_ctx": 32768}


@pytest.mark.parametrize("extension", ["docx", "pptx"])
def test_office_upload_subprocess(tmp_path: Path, extension: str) -> None:
    """The real worker can parse both Office formats within its resource limits."""
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        response = client.post("/api/documents", params={"filename": f"sample.{extension}"},
                               content=export_mission(mission(), extension))
        assert response.status_code == 200, response.text
        assert "Keep source evidence." in " ".join(response.json()["chunks"])


def test_linked_vault_is_rejected(tmp_path: Path) -> None:
    """Approval cannot write through a replaced vault directory."""
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    app = create_app(tmp_path / "test.sqlite3", linked)
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        document = client.post("/api/documents?filename=test.txt", content=b"Test evidence").json()
        assert client.post(f"/api/documents/{document['id']}/approve").status_code == 400
        assert not list(actual.iterdir())


def grouped_presentation(text: str = 'Nested consent step') -> bytes:
    """Build a synthetic nested flow with text, a table and an empty connector."""
    from pptx.util import Inches
    from pptx.enum.shapes import MSO_CONNECTOR
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = 'Before group'
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = 'Issuer step'
    nested = group.shapes.add_group_shape()
    nested.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = text
    table = slide.shapes.add_table(1, 2, 0, 0, Inches(2), Inches(1))
    table.table.cell(0, 0).text, table.table.cell(0, 1).text = 'Holder', 'Verifier'
    # PowerPoint permits graphic frames inside groups; reparent the synthetic table.
    nested.shapes._spTree.insert_element_before(table._element, 'p:extLst')
    group.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, 0, 0, Inches(1), Inches(1))
    slide.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = 'After group'
    output = io.BytesIO()
    deck.save(output)
    return output.getvalue()


def test_grouped_presentation_evidence_preserves_order() -> None:
    """Grouped diagram labels and table cells are retained once in shape order."""
    assert extract_text(grouped_presentation(), 'flow.pptx') == (
        'Slide 1\nBefore group\nIssuer step\nNested consent step\nHolder | Verifier\nAfter group')


def test_grouped_presentation_attachment_retains_evidence(tmp_path: Path) -> None:
    """The public upload route must retain grouped source text in the reference snapshot."""
    app = create_app(tmp_path / 'groups.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        response = client.post('/api/attachments?filename=flow.pptx', content=grouped_presentation())
        assert response.status_code == 200
        attachment = app.state.store.get('attachment', response.json()['id'])
        assert 'Nested consent step' in attachment['text']
        assert 'Holder | Verifier' in attachment['text']


def test_grouped_presentation_cannot_bypass_reference_limit() -> None:
    """Nested text counts against the same attachment budget as top-level text."""
    from src.attachments import MAX_REFERENCE, parse
    with pytest.raises(ValueError):
        parse(grouped_presentation('x' * (MAX_REFERENCE + 1)), 'flow.pptx')


def nested_table_document(nested_text: str = 'Nested source evidence') -> bytes:
    """Create nested Word table content surrounded by ordinary paragraph evidence."""
    doc = Document()
    doc.add_paragraph('Before table')
    outer = doc.add_table(rows=1, cols=1)
    cell = outer.cell(0, 0)
    cell.paragraphs[0].text = 'Outer cell'
    nested = cell.add_table(rows=1, cols=1)
    nested.cell(0, 0).text = nested_text
    cell.add_paragraph('After nested table')
    doc.add_paragraph('After table')
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def test_nested_word_table_evidence_is_not_omitted() -> None:
    """Nested cell content is part of the uploaded source, in document order."""
    text = extract_text(nested_table_document(), 'source.docx')
    assert 'Nested source evidence' in text
    assert text.index('Before table') < text.index('Outer cell') < text.index('Nested source evidence')
    assert text.index('Nested source evidence') < text.index('After nested table') < text.index('After table')
    assert text.count('Nested source evidence') == 1


def test_nested_word_table_counts_toward_reference_budget() -> None:
    """Nested content cannot evade the complete-source attachment limit."""
    from src.attachments import parse, MAX_REFERENCE
    with pytest.raises(ValueError, match='12,000'):
        parse(nested_table_document('x' * (MAX_REFERENCE + 1)), 'source.docx')


def test_nested_word_table_upload_snapshot_retains_evidence(tmp_path: Path) -> None:
    """The authenticated upload path keeps nested evidence for later mission selection."""
    app = create_app(tmp_path / 'nested-word.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        response = client.post('/api/attachments?filename=source.docx', content=nested_table_document())
        assert response.status_code == 200
        assert 'Nested source evidence' in app.state.store.get('attachment', response.json()['id'])['text']


def test_excessive_word_table_nesting_is_rejected() -> None:
    """Deep table trees fail explicitly instead of exhausting Python recursion."""
    doc = Document()
    container = doc
    for _ in range(34):
        container = container.add_table(rows=1, cols=1).cell(0, 0)
    container.text = 'Deep synthetic evidence'
    output = io.BytesIO()
    doc.save(output)
    with pytest.raises(ValueError, match='nesting exceeds'):
        extract_text(output.getvalue(), 'deep.docx')



def test_merged_word_cells_do_not_duplicate_nested_evidence() -> None:
    """Repeated grid references to a merged cell must not multiply nested source text."""
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    merged = table.cell(0, 0).merge(table.cell(1, 1))
    merged.add_table(rows=1, cols=1).cell(0, 0).text = 'Unique nested evidence'
    output = io.BytesIO()
    doc.save(output)
    assert extract_text(output.getvalue(), 'merged.docx').count('Unique nested evidence') == 1
