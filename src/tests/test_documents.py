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
