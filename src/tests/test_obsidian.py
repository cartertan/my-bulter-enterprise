"""Test private Obsidian import using synthetic Markdown and isolated storage.

Inputs: Temporary vaults and fake notes. Outputs: pytest assertions.
Assumptions: No user's vault or platform data is read. Author: Carter Tan.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.obsidian import read_notes, sync_notes
from src.storage import Store


def note(vault: Path, name: str = "one", status: str = "approved", cloud: str = "false", folder: str = "20 Preferences") -> Path:
    """Write a synthetic note to a dedicated test vault."""
    path = vault / folder / (name + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {name}\ntitle: Preference\nstatus: {status}\nscope: shared\ncloud_allowed: {cloud}\nsource: test\n---\nBe concise.\n")
    return path


def test_approved_only_and_inbox_excluded(tmp_path: Path) -> None:
    """Only approved managed notes are included; raw inbox files stay out."""
    note(tmp_path)
    note(tmp_path, "draft", status="draft")
    note(tmp_path, "raw", folder="00 Inbox")
    result = read_notes(tmp_path, set())
    assert len(result) == 1 and result[0]["id"] == "obsidian-one"
    assert result[0]["cloud_allowed"] is False
    assert len(result[0]["source_hash"]) == 64


def test_revocation_and_atomic_validation(tmp_path: Path) -> None:
    """Revocation deactivates cached memory; invalid snapshots do not partly apply."""
    vault = tmp_path / "vault"
    store = Store(tmp_path / "db.sqlite3")
    note(vault)
    sync_notes(store, vault)
    note(vault, status="draft")
    assert sync_notes(store, vault)["deactivated"] == 1
    assert store.get("memory", "obsidian-one")["active"] is False
    note(vault, status="approved")
    note(vault, "bad", cloud="maybe")
    with pytest.raises(ValueError):
        sync_notes(store, vault)
    assert store.get("memory", "obsidian-one")["active"] is False


def test_duplicate_id_and_symlink(tmp_path: Path) -> None:
    """Duplicate IDs and linked notes cannot silently replace approved data."""
    original = note(tmp_path)
    other = tmp_path / "20 Preferences" / "other.md"
    other.write_text(original.read_text())
    with pytest.raises(ValueError, match="Duplicate"):
        read_notes(tmp_path, set())
    other.write_text(original.read_text().replace("id: one", "id: other"))
    (tmp_path / "20 Preferences" / "linked.md").symlink_to(original)
    with pytest.raises(ValueError, match="linked"):
        read_notes(tmp_path, set())


def test_private_owner_validation(tmp_path: Path) -> None:
    """Private notes require a valid owner, never silently become shared."""
    path = note(tmp_path)
    path.write_text(path.read_text().replace("scope: shared", "scope: private\nowner_id: atlas"))
    with pytest.raises(ValueError, match="existing Bulter"):
        read_notes(tmp_path, set())
    assert read_notes(tmp_path, {"atlas"})[0]["owner_id"] == "atlas"


def test_api_readonly_and_missing_vault_blocks_mission(tmp_path: Path) -> None:
    """Imported notes cannot be edited via the API; missing sources block reuse."""
    vault = tmp_path / "vault"
    note(vault)
    app = create_app(tmp_path / "db.sqlite3", vault)
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        assert client.post("/api/obsidian/sync").json()["approved"] == 1
        assert client.put("/api/memories/obsidian-one", json={"title": "No", "content": "No"}).status_code == 409
        bot = client.post("/api/bulters", json={"name": "Atlas", "role": "Test", "model": "fake"}).json()
        vault.rename(tmp_path / "moved-vault")
        assert client.post("/api/missions", json={"prompt": "Hello", "bulter_ids": [bot["id"]]}).status_code == 400


def test_malformed_yaml(tmp_path: Path) -> None:
    """Invalid frontmatter stops import instead of guessing policy."""
    path = note(tmp_path)
    path.write_text("---\nstatus: [\n---\ncontent")
    with pytest.raises(ValueError, match="Invalid note properties"):
        read_notes(tmp_path, set())
