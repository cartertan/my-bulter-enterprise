"""Core policy and mission tests using deterministic providers, not paid APIs.

Inputs: Temporary SQLite databases and synthetic prompts. Outputs: pytest assertions.
Assumptions: No real providers are called. Author: Carter Tan.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import httpx
from fastapi.testclient import TestClient

from src.app import build_context, create_app, eligible_memory
from src.providers import ProviderError, parse_event, request_spec, generate


@pytest.fixture
def client(tmp_path: Path):
    """Provide an isolated app with an authenticated local client."""
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as test_client:
        test_client.headers["x-bulter-token"] = app.state.csrf
        yield test_client


def add_bot(client: TestClient, name: str = "Atlas", provider: str = "ollama", shared: bool = False) -> dict:
    """Create a test Bulter with an explicit provider and model."""
    response = client.post("/api/bulters", json={"name": name, "role": "Reviewer", "provider": provider,
                                                "model": "test-model", "shared_memory": shared})
    assert response.status_code == 200
    return response.json()


def wait_mission(client: TestClient) -> dict:
    """Poll a synthetic mission within a bounded test deadline."""
    for _ in range(100):
        mission = client.get("/api/state").json()["missions"][0]
        if mission["status"] not in ("queued", "running"):
            return mission
        time.sleep(0.01)
    pytest.fail("Mission did not complete within the test deadline.")


def test_local_security(client: TestClient) -> None:
    """Reject unauthorized reads, foreign origins and rebinding hostnames."""
    assert client.get("/api/state", headers={"x-bulter-token": "wrong"}).status_code == 403
    assert client.get("/api/state", headers={"origin": "https://attacker.example"}).status_code == 403
    assert client.get("/api/state", headers={"host": "attacker.example"}).status_code == 403
    assert client.get("/api/state", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.get("/").headers["x-frame-options"] == "DENY"


def test_validation_and_size(client: TestClient) -> None:
    """Reject unknown providers, empty models and oversized request bodies."""
    assert client.post("/api/bulters", json={"name": "Bot", "role": "Test", "provider": "evil", "model": "x"}).status_code == 422
    assert client.post("/api/bulters", json={"name": "Bot", "role": "Test", "model": " "}).status_code == 422
    assert client.post("/api/bulters", content=b"x" * 41000).status_code == 413


def test_memory_scope_and_egress() -> None:
    """Private notes never go to another bot; local-only notes never reach cloud teams."""
    notes = [
        {"id": "a", "owner_id": "alice", "active": True, "cloud_allowed": False},
        {"id": "b", "owner_id": "bob", "active": True, "cloud_allowed": True},
        {"id": "c", "owner_id": None, "active": True, "cloud_allowed": True},
        {"id": "d", "owner_id": None, "active": False, "cloud_allowed": True},
    ]
    alice = {"id": "alice", "shared_memory": False}
    assert [m["id"] for m in eligible_memory(notes, alice, False)] == ["a"]
    assert eligible_memory(notes, alice, True) == []
    alice["shared_memory"] = True
    assert [m["id"] for m in eligible_memory(notes, alice, True)] == ["c"]


def test_cloud_requires_consent_and_key(client: TestClient, monkeypatch) -> None:
    """Reject cloud before starting any model calls when authorization is absent."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    bot = add_bot(client, provider="openai")
    data = {"prompt": "Hello", "bulter_ids": [bot["id"]]}
    assert client.post("/api/missions", json=data).status_code == 400
    data["cloud_consent"] = True
    assert client.post("/api/missions", json=data).status_code == 400
    assert client.get("/api/state").json()["missions"] == []


def test_ordered_handoff_and_snapshot(client: TestClient) -> None:
    """Verify real orchestration order and reference context, using a fake provider."""
    first = add_bot(client)
    second = add_bot(client, "Scribe")
    calls = []

    async def fake_generate(provider: str, model: str, system: str, messages: list, options=None):
        """Capture incoming context and emit synthetic text."""
        calls.append(messages[0]["content"])
        yield "First result" if len(calls) == 1 else "Reviewed result"

    with patch("src.app.generate", fake_generate):
        response = client.post("/api/missions", json={"prompt": "Draft then review", "bulter_ids": [first["id"], second["id"]]})
        assert response.status_code == 200
        mission = wait_mission(client)
    assert mission["status"] == "completed"
    assert [s["name"] for s in mission["steps"]] == ["Atlas", "Scribe"]
    assert "First result" in calls[1]
    assert mission["team"][0]["model"] == "test-model"


def test_no_cross_cloud_memory_transit(client: TestClient, monkeypatch) -> None:
    """Even the local first step excludes local-only notes in a mixed mission."""
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-credential")
    local = add_bot(client, shared=True)
    remote = add_bot(client, "Remote", provider="openai", shared=True)
    client.post("/api/memories", json={"title": "Private policy", "content": "DO_NOT_TRANSMIT", "cloud_allowed": False})
    calls = []

    async def fake_generate(provider: str, model: str, system: str, messages: list, options=None):
        """Observe every step without making a network request."""
        calls.append(messages[0]["content"])
        yield "Safe synthetic output"

    with patch("src.app.generate", fake_generate):
        client.post("/api/missions", json={"prompt": "Hello", "bulter_ids": [local["id"], remote["id"]], "cloud_consent": True})
        mission = wait_mission(client)
    assert mission["status"] == "completed"
    assert all("DO_NOT_TRANSMIT" not in content for content in calls)


def test_cancellation_and_busy_guard(client: TestClient) -> None:
    """A stopped mission keeps partial output and prevents subsequent steps."""
    bot = add_bot(client)

    async def slow_generate(provider: str, model: str, system: str, messages: list, options=None):
        """Leave the upstream request active until cancellation."""
        yield "Partial"
        await asyncio.sleep(20)
        yield "Must not appear"

    with patch("src.app.generate", slow_generate):
        data = {"prompt": "Hello", "bulter_ids": [bot["id"]]}
        mission = client.post("/api/missions", json=data).json()
        time.sleep(0.03)
        assert client.post("/api/missions", json=data).status_code == 409
        assert client.post(f"/api/missions/{mission['id']}/stop").status_code == 200
        result = wait_mission(client)
    assert result["status"] == "cancelled"
    assert result["steps"][0]["output"] == "Partial"


def test_failure_stops_chain(client: TestClient) -> None:
    """Provider errors never become successful handoffs or hidden retries."""
    first, second = add_bot(client), add_bot(client, "Reviewer")

    async def failing_generate(provider: str, model: str, system: str, messages: list, options=None):
        """Emit partial output before a synthetic network failure."""
        yield "Incomplete"
        raise ProviderError("Synthetic connection failure")

    with patch("src.app.generate", failing_generate):
        client.post("/api/missions", json={"prompt": "Hello", "bulter_ids": [first["id"], second["id"]]})
        mission = wait_mission(client)
    assert mission["status"] == "failed"
    assert len(mission["steps"]) == 1
    assert mission["steps"][0]["output"] == "Incomplete"


def test_restart_recovery(tmp_path: Path) -> None:
    """Persist definitions and explicitly mark unfinished missions interrupted."""
    path = tmp_path / "test.sqlite3"
    app = create_app(path)
    app.state.store.put("mission", {"id": "unfinished", "status": "running"})
    second = create_app(path)
    with TestClient(second) as client:
        client.headers["x-bulter-token"] = second.state.csrf
        assert client.get("/api/state").json()["missions"][0]["status"] == "interrupted"


def test_context_limit() -> None:
    """Context overflow is explicit instead of silently losing information."""
    bot = {"name": "Atlas", "role": "Review", "instructions": "Be precise"}
    with pytest.raises(ProviderError, match="Context is too large"):
        build_context(bot, [], "x" * 25000, [])


@pytest.mark.parametrize("provider,event,text,done", [
    ("ollama", {"message": {"content": "hi"}, "done": True}, "hi", True),
    ("openai", {"type": "response.output_text.delta", "delta": "hi"}, "hi", False),
    ("anthropic", {"delta": {"type": "text_delta", "text": "hi"}}, "hi", False),
    ("lmstudio", {"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}, "hi", True),
    ("openrouter", {"choices": [{"delta": {}, "finish_reason": "stop"}]}, "", True),
])
def test_provider_streams(provider: str, event: dict, text: str, done: bool) -> None:
    """Check documented provider response normalization."""
    assert parse_event(provider, event) == (text, done)


def test_paid_payloads(monkeypatch) -> None:
    """API envelopes are provider-specific and keys do not enter prompt bodies."""
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(key, "synthetic-test-credential")
    for provider in ("openai", "anthropic", "openrouter"):
        url, headers, body = request_spec(provider, "model", "Instructions", [{"role": "user", "content": "Hello"}])
        assert url.startswith("https://")
        assert "synthetic-test-credential" not in str(body)
        assert body["stream"] is True
    assert request_spec("openai", "model", "Hi", [])[2]["store"] is False


def test_memory_update(client: TestClient) -> None:
    """Notes can be disabled and invalid owners cannot be saved."""
    data = {"title": "Preference", "content": "Be concise"}
    memory = client.post("/api/memories", json=data).json()
    data["active"] = False
    assert client.put(f"/api/memories/{memory['id']}", json=data).json()["active"] is False
    data["owner_id"] = "missing"
    assert client.post("/api/memories", json=data).status_code == 404


def test_ollama_cloud_model_rejected(client: TestClient) -> None:
    """Known cloud model IDs cannot bypass local-only memory policy."""
    assert client.post("/api/bulters", json={"name": "Cloud disguised as local", "role": "Test",
                                           "model": "example:cloud", "provider": "ollama"}).status_code == 422


@pytest.mark.parametrize("payload,error", [
    ('{"message":{"content":"Hello"},"done":false}\n{"message":{},"done":true}\n', None),
    ('{"message":{"content":"Partial"},"done":false}\n', "before completion"),
    ('not-json\n', "unsupported response"),
    ('{"message":{},"done":true,"done_reason":"length"}\n', "output limit"),
])
def test_transport_completion(payload: str, error: str | None) -> None:
    """Verify stream termination through the actual HTTPX adapter, without a network."""
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=payload))

    async def collect() -> str:
        """Collect the provider's public stream interface."""
        return "".join([chunk async for chunk in generate("ollama", "test-model", "Be concise", [])])

    with patch("src.providers.httpx.AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs)):
        if error:
            with pytest.raises(ProviderError, match=error):
                asyncio.run(collect())
        else:
            assert asyncio.run(collect()) == "Hello"
