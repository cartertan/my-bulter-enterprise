"""Credential boundary regression tests using an in-memory fake Keychain.

Inputs: Synthetic keys and temporary databases. Outputs: pytest assertions.
Assumptions: Never accesses real credentials or makes paid calls. Author: Carter Tan.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.credentials import Credentials, CredentialError
from src.storage import Store
from src.tests.test_app import add_bot, wait_mission


class FakeKeychain:
    """Keep synthetic credentials only in memory for isolated tests."""

    def __init__(self) -> None:
        self.values = {}

    def set_password(self, service: str, provider: str, value: str) -> None:
        """Record one instance-scoped test key."""
        self.values[(service, provider)] = value

    def get_password(self, service: str, provider: str) -> str | None:
        """Read only the requested fake entry."""
        return self.values.get((service, provider))

    def delete_password(self, service: str, provider: str) -> None:
        """Remove the requested fake entry."""
        self.values.pop((service, provider), None)


def fake_key() -> str:
    """Construct a synthetic value rather than embedding a credential-like literal."""
    return "sk-" + "synthetic-for-tests-only-" * 2


def test_instance_isolation_rotation_removal_and_restart(tmp_path: Path) -> None:
    """Fresh databases have separate namespaces; restarting retains the same identity."""
    backend = FakeKeychain()
    first = Credentials(Store(tmp_path / "one.sqlite3"), backend)
    other = Credentials(Store(tmp_path / "two.sqlite3"), backend)
    first.save("openai", fake_key())
    assert first.service != other.service
    assert not other.status("openai")["configured"]
    with pytest.raises(CredentialError):
        other.get("openai")
    restarted = Credentials(Store(tmp_path / "one.sqlite3"), backend)
    assert restarted.get("openai") == fake_key()
    restarted.save("openai", fake_key() + "rotated")
    assert first.get("openai").endswith("rotated")
    restarted.remove("openai")
    assert not first.status("openai")["configured"] and not backend.values
    assert fake_key().encode() not in (tmp_path / "one.sqlite3").read_bytes()


def test_write_only_api_and_cloud_execution(tmp_path: Path) -> None:
    """Only the provider adapter receives the secret; state and snapshots never do."""
    app = create_app(tmp_path / "db.sqlite3", credential_backend=FakeKeychain())
    calls = []

    async def fake(provider, model, system, messages, options=None, api_key=None):
        """Inspect the separate credential parameter without any network call."""
        assert api_key == fake_key()
        assert fake_key() not in json.dumps([system, messages, options])
        calls.append(provider)
        yield "Synthetic response"

    with TestClient(app) as client, patch("src.app.generate", fake):
        client.headers["x-bulter-token"] = app.state.csrf
        response = client.put("/api/credentials/openai", json={"api_key": fake_key()})
        assert response.status_code == 200 and fake_key() not in response.text
        assert client.get("/api/credentials/openai").status_code == 405
        bot = add_bot(client, provider="openai")
        assert client.post("/api/missions", json={"prompt": "Test", "bulter_ids": [bot["id"]], "cloud_consent": True}).status_code == 200
        assert wait_mission(client)["status"] == "completed"
        assert calls == ["openai"]
        assert fake_key() not in client.get("/api/state").text
        assert fake_key() not in client.get("/api/providers").text
        assert client.delete("/api/credentials/openai").status_code == 200
    assert fake_key().encode() not in (tmp_path / "db.sqlite3").read_bytes()


@pytest.mark.parametrize("payload", [{"api_key": ["not-a-string"]}, {"api_key": "token", "extra": "private"},
                                     {"api_key": "sk-ant-oat" + "x" * 40}, {"api_key": "bad\nkey"}])
def test_invalid_input_is_never_echoed(tmp_path: Path, payload: dict) -> None:
    """Bad credential submissions return fixed messages, never validation inputs."""
    app = create_app(tmp_path / "db.sqlite3", credential_backend=FakeKeychain())
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        response = client.put("/api/credentials/anthropic", json=payload)
        assert response.status_code == 400
        assert "input" not in response.json()
        assert str(payload["api_key"]) not in response.text


def test_keychain_denial_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """A locked/denied Keychain never falls back to an environment credential."""
    backend = FakeKeychain()
    credentials = Credentials(Store(tmp_path / "db.sqlite3"), backend)
    credentials.save("openai", fake_key())
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-use-this-fallback")
    with patch.object(backend, "get_password", side_effect=RuntimeError(fake_key())):
        with pytest.raises(CredentialError) as error:
            credentials.get("openai")
        assert fake_key() not in str(error.value)
    with patch.object(backend, "set_password", side_effect=RuntimeError(fake_key())):
        with pytest.raises(CredentialError) as error:
            credentials.save("openai", fake_key())
        assert fake_key() not in str(error.value)


def test_mutation_requires_session_and_idle_mission(tmp_path: Path) -> None:
    """No cross-origin, unauthenticated or active-mission credential mutation."""
    app = create_app(tmp_path / "db.sqlite3", credential_backend=FakeKeychain())
    with TestClient(app) as client:
        assert client.put("/api/credentials/openai", json={"api_key": fake_key()}).status_code == 403
        client.headers["x-bulter-token"] = app.state.csrf
        assert client.put("/api/credentials/openai", json={"api_key": fake_key()}, headers={"Origin": "https://untrusted.example"}).status_code == 403
        assert client.put("/api/credentials/ollama", json={"api_key": fake_key()}).status_code == 400
        assert not app.state.credentials.backend.values
