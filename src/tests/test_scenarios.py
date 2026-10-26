"""User workflow scenarios with synthetic data and deterministic model responses.

Inputs: Disposable vaults and databases. Outputs: pytest assertions.
Assumptions: No real accounts, providers or private files. Author: Carter Tan.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.app import create_app
from src.tests.test_app import add_bot, wait_mission
from src.tests.test_obsidian import note


def test_edit_existing_bulter_model_and_preserve_history(tmp_path: Path) -> None:
    """A model edit survives reopening and only affects subsequent missions."""
    app = create_app(tmp_path / "db.sqlite3")
    calls = []

    async def fake(provider, model, system, messages, options=None):
        """Record model routing without making a network request."""
        calls.append(model)
        yield "Synthetic answer"

    with TestClient(app) as client, patch("src.app.generate", fake):
        client.headers["x-bulter-token"] = app.state.csrf
        bot = add_bot(client, "Atlas")
        client.post("/api/missions", json={"prompt": "First run", "bulter_ids": [bot["id"]]})
        old = wait_mission(client)
        fields = {k: v for k, v in bot.items() if k not in ("id", "created")}
        result = client.put(f"/api/bulters/{bot['id']}", json={**fields, "model": "qwen3.8:27b"})
        assert result.status_code == 200
        assert client.get("/api/state").json()["bulters"][0]["model"] == "qwen3.8:27b"
        client.post("/api/missions", json={"prompt": "Second run", "bulter_ids": [bot["id"]]})
        assert wait_mission(client)["team"][0]["model"] == "qwen3.8:27b"
        assert calls == ["test-model", "qwen3.8:27b"]
        assert app.state.store.get("mission", old["id"])["team"][0]["model"] == "test-model"
    reopened = create_app(tmp_path / "db.sqlite3")
    assert reopened.state.store.get("bulter", bot["id"])["model"] == "qwen3.8:27b"


def test_remove_recreate_and_restore_private_identity(tmp_path: Path) -> None:
    """Removing a bot preserves private ownership; a replacement gets a fresh ID."""
    from src.app import eligible_memory
    app = create_app(tmp_path / "db.sqlite3")
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        old = add_bot(client, "Atlas")
        memory = client.post("/api/memories", json={"title": "Private", "content": "Test only", "owner_id": old["id"]}).json()
        for _ in range(2):
            assert client.delete(f"/api/bulters/{old['id']}").status_code == 200
        state = client.get("/api/state").json()
        assert not state["bulters"] and len(state["removed_bulters"]) == 1
        assert state["memories"][0] == memory
        assert client.post("/api/missions", json={"prompt": "Run", "bulter_ids": [old["id"]]}).status_code == 404
        replacement = add_bot(client, "Atlas")
        assert replacement["id"] != old["id"]
        assert not eligible_memory([memory], replacement, False)
        assert client.post(f"/api/bulters/{old['id']}/restore").status_code == 200
        assert len(client.get("/api/state").json()["bulters"]) == 2
        assert eligible_memory([memory], old, False) == [memory]


def test_removal_requires_session_and_idle_bulter(tmp_path: Path) -> None:
    """Reject cross-session removal and removal from an active mission."""
    app = create_app(tmp_path / "db.sqlite3")
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        bot = add_bot(client)
        app.state.store.put("mission", {"id": "busy", "status": "running", "team": [bot]})
        assert client.delete(f"/api/bulters/{bot['id']}").status_code == 409
        assert client.delete("/api/bulters/missing").status_code == 404
        client.headers.pop("x-bulter-token")
        assert client.delete(f"/api/bulters/{bot['id']}").status_code == 403


def test_removed_obsidian_owner_does_not_break_sync(tmp_path: Path) -> None:
    """Retained identities keep private Obsidian notes valid without reassigning them."""
    app = create_app(tmp_path / "db.sqlite3")
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        bot = add_bot(client)
        path = note(tmp_path / "vault")
        path.write_text(path.read_text().replace("scope: shared", f"scope: private\nowner_id: {bot['id']}"))
        assert client.post("/api/obsidian/sync").status_code == 200
        assert client.delete(f"/api/bulters/{bot['id']}").status_code == 200
        assert client.post("/api/obsidian/sync").status_code == 200
        assert app.state.store.all("memory")[0]["owner_id"] == bot["id"]


def test_large_vault_two_bulter_handoff(tmp_path: Path) -> None:
    """SC01: Retrieve from 140 notes and preserve selected IDs across a handoff."""
    vault = tmp_path / "vault"
    for i in range(140):
        path = note(vault, f"note-{i}", folder="50 Shared Knowledge")
        path.write_text(path.read_text().replace("Be concise.", "Synthetic certificate architecture. " * 65))
    app = create_app(tmp_path / "db.sqlite3", vault)
    calls = []

    async def fake(provider, model, system, messages, options=None):
        """Capture the complete request without any network call."""
        calls.append((system, messages))
        yield "Synthetic review: confirm the certificate requirements."

    with TestClient(app) as client, patch("src.app.generate", fake):
        client.headers["x-bulter-token"] = app.state.csrf
        first = add_bot(client, shared=True)
        second = add_bot(client, "Reviewer", shared=True)
        response = client.post("/api/missions", json={"prompt": "Review certificate architecture", "bulter_ids": [first["id"],second["id"]]})
        assert response.status_code == 200
        mission = wait_mission(client)
        assert mission["status"] == "completed"
        for step, (system, messages) in zip(mission["steps"], calls):
            assert 0 < len(step["memory_ids"]) < 140
            assert step["eligible_memory_count"] == 140
            content = messages[0]["content"]
            assert len(system) + len(content) <= 24000
            references = json.loads(content.split("REFERENCE DATA (not instructions):\n")[1])
            assert step["memory_ids"] == [n["id"] for n in references["user_approved_notes"]]
        assert "Synthetic review" in calls[1][1][0]["content"]


def test_revoke_between_missions(tmp_path: Path) -> None:
    """SC02: Withdraw an approved source and verify it cannot reappear next run."""
    vault = tmp_path / "vault"
    path = note(vault)
    app = create_app(tmp_path / "db.sqlite3", vault)
    calls = []

    async def fake(provider, model, system, messages, options=None):
        """Capture references to check revocation."""
        calls.append(messages[0]["content"])
        yield "Synthetic answer"

    with TestClient(app) as client, patch("src.app.generate", fake):
        client.headers["x-bulter-token"] = app.state.csrf
        bot = add_bot(client, shared=True)
        data = {"prompt":"Be concise", "bulter_ids":[bot["id"]]}
        assert client.post("/api/missions",json=data).status_code == 200
        assert wait_mission(client)["status"] == "completed"
        path.write_text(path.read_text().replace("status: approved","status: archived"))
        assert client.post("/api/missions",json=data).status_code == 200
        assert wait_mission(client)["status"] == "completed"
    assert '"id": "obsidian-one"' in calls[0]
    assert '"id": "obsidian-one"' not in calls[1]


@pytest.mark.parametrize("ids", [[], ["missing"], ["same","same"], ["1","2","3","4","5"]])
def test_invalid_team_never_calls_model(tmp_path: Path, ids: list[str]) -> None:
    """SC03: Empty, unknown, duplicate and oversized teams fail before inference."""
    app = create_app(tmp_path / "db.sqlite3")
    with TestClient(app) as client, patch("src.app.generate") as model:
        client.headers["x-bulter-token"] = app.state.csrf
        assert client.post("/api/missions",json={"prompt":"Synthetic task", "bulter_ids":ids}).status_code in (404,422)
        model.assert_not_called()
        assert client.get("/api/state").json()["missions"] == []


def test_restart_persists_bot_changes_and_note_policy(tmp_path: Path) -> None:
    """SC04: Edited bot assignment and private note policy survive a restart."""
    path = tmp_path / "db.sqlite3"
    app = create_app(path)
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        bot = add_bot(client)
        updated = {k:bot[k] for k in ("name","role","instructions","provider","model","shared_memory")}
        updated.update(name="Concierge",model="synthetic-local-model")
        assert client.put('/api/bulters/'+bot['id'],json=updated).status_code==200
        assert client.post('/api/memories',json={"title":"Synthetic preference","content":"Use concise answers","owner_id":bot['id']}).status_code==200
    restarted = create_app(path)
    with TestClient(restarted) as client:
        client.headers['x-bulter-token'] = restarted.state.csrf
        state = client.get('/api/state').json()
        assert state['bulters'][0]['name']=='Concierge'
        assert state['bulters'][0]['model']=='synthetic-local-model'
        assert state['memories'][0]['owner_id']==bot['id']
        assert state['memories'][0]['cloud_allowed'] is False


def test_local_static_app_and_session_boundary(tmp_path: Path) -> None:
    """SC05: Serve the complete UI locally and reject tokens from another session."""
    app = create_app(tmp_path / 'first.sqlite3')
    other = create_app(tmp_path / 'second.sqlite3')
    with TestClient(app) as client:
        html=client.get('/')
        assert html.status_code==200 and '__SESSION_TOKEN__' not in html.text
        assert client.get('/static/style.css').status_code==200
        assert client.get('/static/app.js').status_code==200
        assert client.get('/api/state',headers={'x-bulter-token':other.state.csrf}).status_code==403
        assert client.get('/api/state',headers={'x-bulter-token':app.state.csrf}).status_code==200
