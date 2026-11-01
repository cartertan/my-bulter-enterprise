"""Regression tests for explicit incomplete-draft review.

Inputs: Synthetic streams and isolated SQLite stores. Outputs: pytest assertions.
Assumptions: No network, credentials, private notes or model inference.
Author: Carter Tan.
"""
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app import bounded_output, create_app
from src.providers import OutputLimitError, ProviderError, parse_event, request_spec
from src.tests.test_app import add_bot, wait_mission


@pytest.mark.parametrize("opt_in", [False, True])
def test_output_limit_review_is_explicit(tmp_path: Path, opt_in: bool) -> None:
    """A reviewer sees flagged partial text only after explicit opt-in."""
    app = create_app(tmp_path / "test.sqlite3")
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Truncate the author, then record the reviewer context."""
        calls.append((system, messages))
        if len(calls) == 1:
            yield "Synthetic incomplete draft"
            raise OutputLimitError("Output limit reached")
        yield "Missing sections prevent acceptance."

    with TestClient(app) as client, patch("src.app.generate", stream):
        client.headers["x-bulter-token"] = app.state.csrf
        assert client.get("/api/state").json()["capabilities"]["partial_output_review"] is True
        bots = [add_bot(client), add_bot(client, "Reviewer")]
        response = client.post("/api/missions", json={"prompt": "Review a draft",
            "bulter_ids": [b["id"] for b in bots], "review_partial_output": opt_in})
        assert response.status_code == 200
        result = wait_mission(client)
        assert result["acceptance_status"] == "not_assessed"
        assert result["steps"][0]["status"] == "partial"
        assert result["steps"][0]["error_code"] == "output_limit"
        assert result["status"] == ("completed_with_issues" if opt_in else "failed")
        assert len(calls) == (2 if opt_in else 1)
        if opt_in:
            assert '"status": "partial"' in calls[1][1][0]["content"]
            assert "previous output is explicitly incomplete" in calls[1][0]
            assert result["steps"][1]["status"] == "completed"
        # A finished review cannot turn an incomplete mission into an Office deliverable.
        assert client.get(f"/api/missions/{result['id']}/export/pptx").status_code == 400
        assert app.state.store.get("mission", result["id"]) == result


@pytest.mark.parametrize("failure", ["network", "empty", "last_step"])
def test_partial_review_does_not_hide_other_failures(tmp_path: Path, failure: str) -> None:
    """Network, empty output and final-step limits still fail."""
    app = create_app(tmp_path / "test.sqlite3")
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Emit a bounded synthetic failure selected by the test."""
        calls.append(model)
        if failure == "empty":
            raise OutputLimitError("Output limit reached")
        yield "Partial evidence"
        if failure == "network":
            raise ProviderError("Network failure")
        if failure != "last_step" or len(calls) == 2:
            raise OutputLimitError("Output limit reached")

    with TestClient(app) as client, patch("src.app.generate", stream):
        client.headers["x-bulter-token"] = app.state.csrf
        bots = [add_bot(client), add_bot(client, "Reviewer")]
        client.post("/api/missions", json={"prompt": "Review",
            "bulter_ids": [b["id"] for b in bots], "review_partial_output": True})
        result = wait_mission(client)
        assert result["status"] == "failed"
        assert len(calls) == (2 if failure == "last_step" else 1)


def test_character_cap_is_bounded_and_reviewed(tmp_path: Path) -> None:
    """A large stream chunk cannot persist more than the 16k text limit."""
    app = create_app(tmp_path / "test.sqlite3")
    calls = []
    closed = []

    async def stream(provider, model, system, messages, **kwargs):
        """Return one oversized chunk, then a short review."""
        calls.append(model)
        if len(calls) == 2:
            assert closed == [True]  # Close the prior upstream before invoking a reviewer.
        try:
            yield "a" * 20000 if len(calls) == 1 else "Incomplete."
        finally:
            closed.append(True)

    with TestClient(app) as client, patch("src.app.generate", stream):
        client.headers["x-bulter-token"] = app.state.csrf
        bots = [add_bot(client), add_bot(client, "Reviewer")]
        client.post("/api/missions", json={"prompt": "Review", "bulter_ids": [b["id"] for b in bots], "review_partial_output": True})
        result = wait_mission(client)
        assert result["status"] == "completed_with_issues"
        assert len(result["steps"][0]["output"]) == 16000
        assert len(calls) == 2


@pytest.mark.parametrize("mode,count", [("reference", 1), ("edit", 2), ("reuse_design", 2), ("placeholders", 2)])
def test_partial_review_scope(tmp_path: Path, mode: str, count: int) -> None:
    """Reject unsupported combinations before model execution."""
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        result = client.post("/api/missions", json={"prompt": "Review", "bulter_ids": [str(i) for i in range(count)],
            "attachment_mode": mode, "review_partial_output": True})
        assert result.status_code == 422
        assert not app.state.store.all("mission")


@pytest.mark.parametrize("provider,event", [
    ("ollama", {"done": True, "done_reason": "length"}),
    ("lmstudio", {"choices": [{"finish_reason": "length"}]}),
    ("openrouter", {"choices": [{"finish_reason": "length"}]}),
    ("openai", {"type": "response.incomplete", "response": {"incomplete_details": {"reason": "max_output_tokens"}}}),
    ("anthropic", {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}}),
])
def test_known_provider_limits_are_typed(provider: str, event: dict) -> None:
    """Only explicit provider length exhaustion is recoverable."""
    with pytest.raises(OutputLimitError):
        parse_event(provider, event)


def test_unknown_incomplete_reason_is_not_recoverable() -> None:
    """A filtered or unknown OpenAI interruption must not continue a chain."""
    with pytest.raises(ProviderError) as caught:
        parse_event("openai", {"type": "response.incomplete", "response": {"incomplete_details": {"reason": "content_filter"}}})
    assert not isinstance(caught.value, OutputLimitError)


@pytest.mark.parametrize("provider", ["ollama", "lmstudio", "openai", "anthropic", "openrouter"])
def test_output_configuration_reaches_every_provider(provider: str) -> None:
    """Configured output budgets are not silently replaced by hardcoded defaults."""
    _, _, body = request_spec(provider, "synthetic", "system", [], {"output_tokens": 4096}, api_key="synthetic")
    actual = body["options"]["num_predict"] if provider == "ollama" else body["max_output_tokens" if provider == "openai" else "max_tokens"]
    assert actual == 4096


@pytest.mark.parametrize("text", ['"' * 20000, "\\" * 20000, "\x00" * 6000, "界🙂" * 12000])
def test_handoff_budget_counts_json_escaping(text: str) -> None:
    """Escaped controls cannot overflow reserved reviewer space."""
    import json
    retained, exceeded = bounded_output(text, 1234)
    assert exceeded
    assert text.startswith(retained)
    assert len(json.dumps(retained, ensure_ascii=False)) - 2 <= 1234
    assert len(json.dumps(text[:len(retained) + 1], ensure_ascii=False)) - 2 > 1234


@pytest.mark.parametrize("count", [2, 3, 4])
def test_large_reference_reaches_every_reviewer(tmp_path: Path, count: int) -> None:
    """A 12k reference and long escaped drafts retain all sources in every call."""
    app = create_app(tmp_path / "test.sqlite3")
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Force author limits, then return a bounded final review."""
        calls.append(messages[0]["content"])
        assert len(system) + len(messages[0]["content"]) <= 24000
        assert "SOURCE_START" in calls[-1] and "SOURCE_END" in calls[-1]
        yield ('"\\\n' * 10000) if len(calls) < count else "Missing content prevents acceptance."

    with TestClient(app) as client, patch("src.app.generate", stream):
        client.headers["x-bulter-token"] = app.state.csrf
        bots = [add_bot(client, f"Agent {index}") for index in range(count)]
        # Connector snapshots exercise the same immutable reference handoff path.
        app.state.store.put("connector_evidence", {"id": "source", "text": "SOURCE_START" + "x" * 12000 + "SOURCE_END"})
        response = client.post("/api/missions", json={"prompt": "Review all source evidence",
            "bulter_ids": [bot["id"] for bot in bots], "evidence_ids": ["source"],
            "review_partial_output": True})
        assert response.status_code == 200
        result = wait_mission(client)
        assert len(calls) == count
        assert result["status"] == "completed_with_issues"
        assert all(step["status"] == "partial" for step in result["steps"][:-1])
        assert result["steps"][-1]["status"] == "completed"
        assert result["acceptance_status"] == "not_assessed"


def test_review_space_rejected_before_inference(tmp_path: Path) -> None:
    """Insufficient review capacity cannot consume a provider call."""
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as client, patch("src.app.generate") as generate_mock:
        client.headers["x-bulter-token"] = app.state.csrf
        bots = [add_bot(client, str(index)) for index in range(4)]
        app.state.store.put("connector_evidence", {"id": "source", "text": "x" * 19000})
        response = client.post("/api/missions", json={"prompt": "Review",
            "bulter_ids": [bot["id"] for bot in bots], "evidence_ids": ["source"]})
        assert response.status_code == 400
        assert "review space" in response.json()["detail"]
        generate_mock.assert_not_called()
        assert not app.state.store.all("mission")
