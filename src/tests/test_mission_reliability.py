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


def failed_review(client: TestClient, app) -> dict:
    """Create a real persisted checkpoint with one complete and one failed call."""
    bots = [add_bot(client, "Author"), add_bot(client, "Reviewer")]
    calls = []

    async def stream(*args, **kwargs):
        """Fail the reviewer after retaining its partial draft."""
        calls.append(True)
        if len(calls) == 1:
            yield "Completed author evidence"
        else:
            yield "Unfinished review"
            raise ProviderError("Synthetic connection failure")

    with patch("src.app.generate", stream):
        response = client.post("/api/missions", json={"prompt": "Review evidence", "bulter_ids": [b["id"] for b in bots]})
        assert response.status_code == 200
        mission = wait_mission(client)
        assert mission["status"] == "failed"
        return mission


@pytest.mark.parametrize("crashed", [False, True])
def test_resume_after_restart_preserves_history_and_skips_completed(tmp_path: Path, crashed: bool) -> None:
    """Recovery is durable, explicit and single-use after a process restart."""
    path = tmp_path / "test.sqlite3"
    app = create_app(path)
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        original = failed_review(client, app)
    if crashed:
        original["status"] = "running"
        original["steps"][-1]["status"] = "running"
        app.state.store.put("mission", original)
    fresh = create_app(path)
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """The resumed reviewer receives the original complete author draft."""
        calls.append(system)
        assert "Completed author evidence" in messages[0]["content"]
        assert "Unfinished review" not in messages[0]["content"]
        yield "New completed review"

    with TestClient(fresh) as client, patch("src.app.generate", stream):
        client.headers["x-bulter-token"] = fresh.state.csrf
        if crashed:
            original = fresh.state.store.get("mission", original["id"])
            assert original["status"] == "interrupted"
        response = client.post(f"/api/missions/{original['id']}/resume", json={})
        assert response.status_code == 200
        child = wait_mission(client)
        assert child["status"] == "completed"
        assert child["parent_mission_id"] == original["id"]
        assert child["steps"][0] == original["steps"][0]
        assert len(calls) == 1
        assert fresh.state.store.get("mission", original["id"]) == original
        assert client.post(f"/api/missions/{original['id']}/resume", json={}).status_code == 409


@pytest.mark.parametrize("change", ["source", "source_changed", "memory", "memory_changed", "bot", "cloud", "limit"])
def test_resume_revalidates_policy_before_calls(tmp_path: Path, change: str) -> None:
    """Stale sources, revoked memory and missing consent cannot be reused."""
    from src.app import revision_hash
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        parent = failed_review(client, app)
        if change == "source":
            parent["source_revisions"]["connector_evidence"] = {"missing": "old"}
        elif change == "source_changed":
            parent["source_revisions"]["connector_evidence"] = {"changed": revision_hash({"id": "changed", "text": "original"})}
            app.state.store.put("connector_evidence", {"id": "changed", "text": "edited"})
        elif change in {"memory", "memory_changed"}:
            note = {"id": "revoked", "active": True, "owner_id": parent["team"][0]["id"], "cloud_allowed": False}
            parent["steps"][0]["memory_revisions"] = {"revoked": revision_hash(note)}
            app.state.store.put("memory", {**note, "active": change == "memory_changed", "content": "edited"})
        elif change == "bot":
            bot = parent["team"][0]
            app.state.store.put("bulter", {**bot, "instructions": "changed"})
        elif change == "cloud":
            parent["cloud"] = True
        else:
            parent["resume_attempt"] = 3
        app.state.store.put("mission", parent)
        with patch("src.app.generate") as generate_mock:
            response = client.post(f"/api/missions/{parent['id']}/resume", json={})
            assert response.status_code == (400 if change == "cloud" else 409)
            generate_mock.assert_not_called()
            assert len(app.state.store.all("mission")) == 1


def test_cancel_resumed_call_keeps_both_attempts(tmp_path: Path) -> None:
    """Cancellation during recovery preserves the checkpoint and new partial text."""
    import asyncio
    app = create_app(tmp_path / "test.sqlite3")

    async def stream(*args, **kwargs):
        """Keep the resumed provider open until cancelled."""
        yield "New partial review"
        await asyncio.Event().wait()

    with TestClient(app) as client:
        client.headers["x-bulter-token"] = app.state.csrf
        parent = failed_review(client, app)
        with patch("src.app.generate", stream):
            response = client.post(f"/api/missions/{parent['id']}/resume", json={})
            assert response.status_code == 200
            child_id = response.json()["id"]
            assert client.post(f"/api/missions/{parent['id']}/resume", json={}).status_code == 409
            stopped = client.post(f"/api/missions/{child_id}/stop").json()
            assert stopped["status"] == "cancelled"
            assert app.state.store.get("mission", parent["id"]) == parent


def test_required_notes_are_reserved_and_provenance_persisted(tmp_path: Path) -> None:
    """An unrelated required note survives a large draft and reaches review."""
    app = create_app(tmp_path / "test.sqlite3")
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Assert pinned evidence is intact in both calls."""
        calls.append(messages[0]["content"])
        assert "REQUIRED_PREFERENCE" in calls[-1]
        assert "DEMO_CONTENT" not in calls[-1]
        yield "x" * 20000 if len(calls) == 1 else "Review complete"

    with TestClient(app) as client, patch("src.app.generate", stream):
        client.headers["x-bulter-token"] = app.state.csrf
        bots = [add_bot(client, "Author", shared=True), add_bot(client, "Reviewer", shared=True)]
        saved = client.post('/api/memories', json={"title": "Writing preference", "content": "REQUIRED_PREFERENCE" + "a" * 2900, "category": "preference"}).json()
        client.post('/api/memories', json={"title": "Review", "content": "DEMO_CONTENT", "category": "demo"})
        result = client.post('/api/missions', json={"prompt": "Review", "bulter_ids": [b["id"] for b in bots],
            "required_memory_ids": [saved["id"]], "review_partial_output": True})
        assert result.status_code == 200
        mission = wait_mission(client)
        assert len(calls) == 2
        for step in mission["steps"]:
            assert step["memory_ids"] == [saved["id"]]
            assert step["memory_provenance"][0]["category"] == "preference"
            assert step["memory_provenance"][0]["revision"] == mission["required_memory_revisions"][saved["id"]]


def test_required_memory_preflight_rejects_before_generation(tmp_path: Path) -> None:
    """A revoked selected note fails before any model receives the task."""
    app = create_app(tmp_path / "test.sqlite3")
    with TestClient(app) as client, patch('src.app.generate') as generate_mock:
        client.headers['x-bulter-token'] = app.state.csrf
        bot = add_bot(client, shared=True)
        response = client.post('/api/missions', json={"prompt": "Review", "bulter_ids": [bot["id"]], "required_memory_ids": ["missing"]})
        assert response.status_code == 400
        generate_mock.assert_not_called()
        assert not app.state.store.all('mission')


def test_sections_isolate_handoffs_and_resume_from_exact_checkpoint(tmp_path: Path) -> None:
    """A failed second-section review never reruns completed first-section work."""
    path = tmp_path / 'sections.sqlite3'
    app = create_app(path)
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Generate two independent drafts; interrupt the last reviewer."""
        content = messages[0]['content']
        calls.append(content)
        assert 'SHARED_SOURCE' in content
        if len(calls) <= 2:
            assert 'CURRENT SECTION ONLY:\nIssuance' in content
        else:
            assert 'CURRENT SECTION ONLY:\nPresentation' in content
            assert 'ISSUANCE_DRAFT' not in content
            assert 'ISSUANCE_REVIEW' not in content
        if len(calls) == 4:
            yield 'Interrupted final review'
            raise ProviderError('Synthetic interruption')
        yield ['ISSUANCE_DRAFT', 'ISSUANCE_REVIEW', 'PRESENTATION_DRAFT'][len(calls) - 1]

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        app.state.store.put('connector_evidence', {'id': 'source', 'text': 'SHARED_SOURCE'})
        response = client.post('/api/missions', json={'prompt': 'Explain national wallet flows',
            'sections': ['Issuance', 'Presentation'], 'bulter_ids': [bot['id'] for bot in bots], 'evidence_ids': ['source']})
        assert response.status_code == 200
        original = wait_mission(client)
        assert original['planned_calls'] == 4 and len(calls) == 4
        assert original['status'] == 'failed'
        assert [step['section_id'] for step in original['steps']] == ['section-1', 'section-1', 'section-2', 'section-2']
    fresh = create_app(path)
    recovered_calls = []

    async def recovery(provider, model, system, messages, **kwargs):
        """Only the unfinished review runs with its own section's draft."""
        recovered_calls.append(messages)
        content = messages[0]['content']
        assert 'PRESENTATION_DRAFT' in content and 'ISSUANCE_DRAFT' not in content
        yield 'Final review'

    with TestClient(fresh) as client, patch('src.app.generate', recovery):
        client.headers['x-bulter-token'] = fresh.state.csrf
        assert client.post(f"/api/missions/{original['id']}/resume", json={}).status_code == 200
        child = wait_mission(client)
        assert child['status'] == 'completed' and len(recovered_calls) == 1
        assert child['steps'][:3] == original['steps'][:3]
        assert child['steps'][3]['draft_revision'] == 2
        assert child['steps'][3]['source_revision'] == original['steps'][3]['source_revision']
        assert child['steps'][3]['review_state'] == 'not_assessed'
        assert fresh.state.store.get('mission', original['id']) == original
        assert client.get(f"/api/missions/{child['id']}/export/pptx").status_code == 400


@pytest.mark.parametrize('sections,mode', [(['Duplicate', 'Duplicate'], 'reference'),
    ([''], 'reference'), (['x' * 1001], 'reference'), ([str(i) for i in range(7)], 'reference'),
    (['One'], 'edit'), (['One'], 'reuse_design'), (['One'], 'placeholders')])
def test_invalid_section_plans_rejected_before_inference(tmp_path: Path, sections: list[str], mode: str) -> None:
    """Explicit bounds reject unsupported and unbounded call plans."""
    app = create_app(tmp_path / 'sections.sqlite3')
    with TestClient(app) as client, patch('src.app.generate') as generate_mock:
        client.headers['x-bulter-token'] = app.state.csrf
        response = client.post('/api/missions', json={'prompt': 'Review', 'bulter_ids': ['one'], 'sections': sections, 'attachment_mode': mode})
        assert response.status_code == 422
        generate_mock.assert_not_called()


@pytest.mark.parametrize('variant', ['valid', 'fail', 'unknown', 'missing', 'duplicate', 'stale', 'forged_identity', 'invented_quote', 'no_quote', 'partial_author', 'duplicate_key', 'prose'])
def test_structured_review_fails_closed(variant: str) -> None:
    """Only complete, exact-draft assessments can claim criterion-level success."""
    import json
    from src.app import draft_hash, validate_draft_review
    author = {'bulter_id': 'author', 'output': 'Issuance uses explicit consent.', 'status': 'completed',
              'section_id': 'section-1', 'draft_revision': 1}
    item = {'criterion_id': 'criterion-1', 'result': 'pass', 'reason': 'Consent is stated',
            'evidence_quotes': ['explicit consent']}
    payload = {'draft_hash': draft_hash(author['output']), 'criteria': [item]}
    if variant in {'fail', 'unknown'}:
        item.update(result=variant, evidence_quotes=[])
    elif variant == 'missing':
        payload['criteria'] = []
    elif variant == 'duplicate':
        payload['criteria'].append(dict(item))
    elif variant == 'stale':
        payload['draft_hash'] = '0' * 64
    elif variant == 'forged_identity':
        payload['reviewer_id'] = 'another reviewer'
    elif variant == 'invented_quote':
        item['evidence_quotes'] = ['Invented external source']
    elif variant == 'no_quote':
        item['evidence_quotes'] = []
    elif variant == 'partial_author':
        author['status'] = 'partial'
    output = json.dumps(payload)
    if variant == 'duplicate_key':
        output = output.replace('"result": "pass"', '"result": "fail", "result": "pass"')
    elif variant == 'prose':
        output = 'Everyone agrees this passes.'
    result = validate_draft_review(output, author, ['Require consent'], 'actual-reviewer')
    assert result['reviewer_id'] == 'actual-reviewer'
    assert result['draft_hash'] == draft_hash(author['output'])
    assert result['state'] == ('criteria_pass' if variant == 'valid' else 'needs_revision' if variant in {'fail', 'unknown'} else 'invalid')
    expected_codes = {'missing': 'review_schema', 'duplicate': 'review_criteria', 'stale': 'review_draft_hash',
        'forged_identity': 'review_schema', 'invented_quote': 'review_evidence', 'no_quote': 'review_missing_evidence',
        'partial_author': 'review_incomplete_draft', 'duplicate_key': 'review_json_fields', 'prose': 'review_json'}
    assert result.get('error_code') == expected_codes.get(variant)
    if variant in expected_codes:
        assert result['criteria'] == [] and result['error']



@pytest.mark.parametrize('verdict', ['pass', 'fail', 'invalid'])
def test_structured_review_mission_records_identity_and_keeps_acceptance_separate(tmp_path: Path, verdict: str) -> None:
    """Validated model assessments remain separate from execution and approval."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'review.sqlite3')
    calls = []
    draft = 'Wallet issuance requires explicit consent.'

    async def stream(provider, model, system, messages, **kwargs):
        """Return a synthetic draft and a criterion-bound reviewer response."""
        calls.append(messages[0]['content'])
        assert 'criterion-1' in calls[-1]
        if len(calls) == 1:
            assert 'response_schema' not in kwargs['options']
            yield draft
        elif verdict == 'invalid':
            assert kwargs['options']['response_schema']['properties']['draft_hash']['const'] == draft_hash(draft)
            yield 'Author and Reviewer both agree.'
        else:
            assert draft_hash(draft) in calls[-1]
            assert kwargs['options']['response_schema']['properties']['draft_hash']['const'] == draft_hash(draft)
            yield json.dumps({'draft_hash': draft_hash(draft), 'criteria': [
                {'criterion_id': 'criterion-1', 'result': verdict, 'reason': 'Synthetic assessment',
                 'evidence_quotes': ['explicit consent'] if verdict == 'pass' else []}]})

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        response = client.post('/api/missions', json={'prompt': 'Draft and review', 'bulter_ids': [b['id'] for b in bots],
            'review_criteria': ['Require explicit consent']})
        assert response.status_code == 200
        mission = wait_mission(client)
        assert mission['status'] == ('completed' if verdict == 'pass' else 'completed_with_issues')
        assert mission['acceptance_status'] == 'not_assessed'
        assert all('response_schema' not in b for b in mission['team'])
        record = mission['steps'][1]['review']
        assert record['reviewer_id'] == bots[1]['id'] and record['author_id'] == bots[0]['id']
        assert record['draft_hash'] == draft_hash(draft)
        assert client.get(f"/api/missions/{mission['id']}/export/pptx").status_code == 400


def timed_outline(seconds=1620, discussion=300) -> dict:
    """Create a synthetic one-slide outline for deterministic timing checks."""
    return {'slides': [{'slide_id': 'slide-1', 'title': 'Wallet flow', 'body': 'Explicit consent',
                        'speaker_notes': 'Explain the flow', 'duration_seconds': seconds}],
            'discussion_seconds': discussion}


@pytest.mark.parametrize('seconds,discussion,state,total', [(1620, 300, 'exceeded', 1920),
    (1500, 300, 'pass', 1800), (1499, 300, 'pass', 1799)])
def test_timing_uses_integer_arithmetic_including_discussion(seconds: int, discussion: int, state: str, total: int) -> None:
    """27 plus 5 fails a 30-minute budget, while the exact boundary passes."""
    import json
    from src.app import validate_timing
    check = validate_timing(json.dumps(timed_outline(seconds, discussion)), 1800)
    assert check['state'] == state and check['total_seconds'] == total
    assert check['overrun_seconds'] == max(0, total - 1800)


@pytest.mark.parametrize('variant', ['boolean', 'float', 'negative', 'string', 'missing', 'duplicate', 'extra_total', 'partial', 'prose'])
def test_invalid_timing_never_passes(variant: str) -> None:
    """Missing, coerced and ambiguous timing cannot be treated as zero or trusted totals."""
    import json
    from src.app import validate_timing
    payload = timed_outline()
    if variant in {'boolean', 'float', 'negative', 'string'}:
        payload['slides'][0]['duration_seconds'] = {'boolean': True, 'float': 1.5, 'negative': -10, 'string': '120'}[variant]
    elif variant == 'missing':
        del payload['discussion_seconds']
    elif variant == 'duplicate':
        payload['slides'].append(dict(payload['slides'][0]))
    elif variant == 'extra_total':
        payload['total_seconds'] = 1200
    text = 'This presentation takes 30 minutes' if variant == 'prose' else json.dumps(payload)
    assert validate_timing(text, 1800, complete=variant != 'partial')['state'] == 'invalid'


def test_reviewer_cannot_override_failed_timing(tmp_path: Path) -> None:
    """A model pass on an overlong outline leaves the run unresolved."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'timing.sqlite3')
    draft = json.dumps(timed_outline())
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Return a false-positive review to exercise the deterministic override."""
        calls.append(messages[0]['content'])
        if len(calls) == 1:
            assert '1800 seconds INCLUDING discussion' in calls[-1]
            yield draft
        else:
            assert '"total_seconds": 1920' in calls[-1]
            yield json.dumps({'draft_hash': draft_hash(draft), 'criteria': [{'criterion_id': 'criterion-1',
                'result': 'pass', 'reason': 'Model incorrectly claims this fits', 'evidence_quotes': ['Explicit consent']}]})

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        response = client.post('/api/missions', json={'prompt': 'Create a wallet presentation',
            'bulter_ids': [b['id'] for b in bots], 'review_criteria': ['Fits allotted time'], 'duration_budget_seconds': 1800})
        assert response.status_code == 200
        mission = wait_mission(client)
        assert mission['status'] == 'completed_with_issues'
        assert mission['acceptance_status'] == 'not_assessed'
        assert mission['steps'][0]['timing_check']['overrun_seconds'] == 120
        assert mission['steps'][1]['review']['state'] == 'needs_revision'
        assert mission['steps'][1]['review']['blocking_checks'] == ['presentation_timing']
        assert client.get(f"/api/missions/{mission['id']}/export/pptx").status_code == 400


@pytest.mark.parametrize('eventual_pass', [True, False])
def test_bounded_revision_preserves_history_and_rechecks_new_draft(tmp_path: Path, eventual_pass: bool) -> None:
    """Each explicit revision runs both agents, binds new text and stops at its cap."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'revisions.sqlite3')
    calls = []
    drafts = []

    async def stream(provider, model, system, messages, **kwargs):
        """Return distinct drafts and controlled reviewer verdicts."""
        calls.append(messages[0]['content'])
        if len(calls) % 2:
            if drafts:
                assert drafts[-1] in calls[-1]
                assert 'Produce a complete replacement draft' in calls[-1]
            drafts.append(f'Draft {len(drafts) + 1}: explicit consent')
            yield drafts[-1]
        else:
            verdict = 'pass' if eventual_pass and len(drafts) > 1 else 'fail'
            yield json.dumps({'draft_hash': draft_hash(drafts[-1]), 'criteria': [{'criterion_id': 'criterion-1',
                'result': verdict, 'reason': 'Synthetic finding', 'evidence_quotes': ['explicit consent']}]})

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        assert client.post('/api/missions', json={'prompt': 'Draft and review', 'bulter_ids': [b['id'] for b in bots],
            'review_criteria': ['Include consent']}).status_code == 200
        original = wait_mission(client)
        assert original['status'] == 'completed_with_issues'
        assert client.post(f"/api/missions/{original['id']}/revise", json={}).status_code == 200
        child = wait_mission(client)
        assert child['revision_round'] == 1 and len(calls) == 4
        assert child['attempt_kind'] == 'revision'
        assert child['steps'][1]['review']['draft_hash'] == draft_hash(drafts[-1])
        assert child['steps'][1]['review']['draft_hash'] != original['steps'][1]['review']['draft_hash']
        assert child['acceptance_status'] == 'not_assessed'
        assert app.state.store.get('mission', original['id']) == original
        assert client.post(f"/api/missions/{original['id']}/revise", json={}).status_code == 409
        if eventual_pass:
            assert child['status'] == 'completed'
            assert client.post(f"/api/missions/{child['id']}/revise", json={}).status_code == 409
        else:
            assert client.post(f"/api/missions/{child['id']}/revise", json={}).status_code == 200
            final = wait_mission(client)
            assert final['revision_round'] == 2 and final['status'] == 'completed_with_issues'
            assert client.post(f"/api/missions/{final['id']}/revise", json={}).status_code == 409
            assert len(calls) == 6


@pytest.mark.parametrize('blocker', ['cloud_consent', 'oversized_feedback', 'changed_source'])
def test_revision_blocks_before_calls_on_policy_or_budget_failure(tmp_path: Path, blocker: str) -> None:
    """Explicit revision cannot bypass consent, source validation or context limits."""
    app = create_app(tmp_path / 'revision-policy.sqlite3')
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        parent = failed_review(client, app)
        parent.update(status='completed_with_issues', review_criteria=['Review consent'])
        if blocker == 'cloud_consent':
            parent['cloud'] = True
        elif blocker == 'oversized_feedback':
            parent['steps'][0]['output'] = 'x' * 24000
        else:
            parent['source_revisions']['connector_evidence'] = {'missing': 'old-hash'}
        app.state.store.put('mission', parent)
        with patch('src.app.generate') as generate_mock:
            response = client.post(f"/api/missions/{parent['id']}/revise", json={})
            assert response.status_code == (409 if blocker == 'changed_source' else 400)
            generate_mock.assert_not_called()
            assert len(app.state.store.all('mission')) == 1


@pytest.mark.parametrize('variant', ['valid', 'unknown_source', 'invented_quote', 'missing_claims', 'partial', 'truncated'])
def test_source_reference_validation_is_evidence_bound(variant: str) -> None:
    """Source IDs and quotes must exist; passing references never assert truth."""
    import json
    from src.app import validate_sources
    outline = timed_outline(120, 30)
    claim = {'text': 'The issuer obtains consent', 'evidence': [{'source_id': 'source-1', 'quote': 'explicit consent'}]}
    outline['slides'][0]['claims'] = [claim]
    sources = [{'id': 'source-1', 'content': 'Issuance requires explicit consent.', 'truncated': variant == 'truncated'}]
    if variant == 'unknown_source':
        claim['evidence'][0]['source_id'] = 'fabricated'
    elif variant == 'invented_quote':
        claim['evidence'][0]['quote'] = 'Invented statement'
    elif variant == 'missing_claims':
        outline['slides'][0]['claims'] = []
    check = validate_sources(json.dumps(outline), [], sources, variant != 'partial')
    assert check['state'] == ('references_valid' if variant == 'valid' else 'invalid')
    assert check['factual_accuracy'] == 'not_assessed'


def test_fabricated_source_blocks_model_pass(tmp_path: Path) -> None:
    """A passing reviewer cannot override an invented author source identifier."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'sources.sqlite3')
    outline = timed_outline(120, 30)
    outline['slides'][0]['claims'] = [{'text': 'Consent is required',
        'evidence': [{'source_id': 'invented-source', 'quote': 'explicit consent'}]}]
    draft = json.dumps(outline)
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Reproduce the original hallucinated-reference failure with synthetic inputs."""
        calls.append(messages[0]['content'])
        assert 'SOURCE REGISTER' in calls[-1]
        if len(calls) == 1:
            yield draft
        else:
            assert 'SOURCE REFERENCE CHECK' in calls[-1]
            yield json.dumps({'draft_hash': draft_hash(draft), 'criteria': [{'criterion_id': 'criterion-1',
                'result': 'pass', 'reason': 'Model overlooked the fabricated source', 'evidence_quotes': ['Consent is required']}]})

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        source = client.post('/api/attachments?filename=source.txt', content=b'Issuance requires explicit consent.').json()
        response = client.post('/api/missions', json={'prompt': 'Prepare a sourced presentation',
            'bulter_ids': [b['id'] for b in bots], 'attachment_ids': [source['id']],
            'duration_budget_seconds': 1800, 'review_criteria': ['Use supported claims'], 'require_source_citations': True})
        assert response.status_code == 200
        mission = wait_mission(client)
        assert mission['source_register'][0]['source_id'] == source['id']
        assert mission['source_register'][0]['content_sha256'] == draft_hash('Issuance requires explicit consent.')
        assert mission['steps'][0]['source_check']['state'] == 'invalid'
        assert mission['steps'][1]['review']['blocking_checks'] == ['source_references']
        assert mission['steps'][1]['review']['state'] == 'needs_revision'
        assert mission['status'] == 'completed_with_issues'
        assert mission['acceptance_status'] == 'not_assessed'


@pytest.mark.parametrize('truncated', [False, True])
def test_citation_mode_requires_complete_sources_before_calls(tmp_path: Path, truncated: bool) -> None:
    """Empty selection and truncated connector snapshots reject before inference."""
    app = create_app(tmp_path / 'source-preflight.sqlite3')
    with TestClient(app) as client, patch('src.app.generate') as generate_mock:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        if truncated:
            app.state.store.put('connector_evidence', {'id': 'source', 'content': 'incomplete', 'truncated': True})
        response = client.post('/api/missions', json={'prompt': 'Prepare a sourced presentation',
            'bulter_ids': [b['id'] for b in bots], 'evidence_ids': ['source'] if truncated else [],
            'duration_budget_seconds': 1800, 'review_criteria': ['Use supported claims'], 'require_source_citations': True})
        assert response.status_code == 400
        generate_mock.assert_not_called()

@pytest.mark.parametrize('blocker', ['none', 'last_section_budget', 'section_history'])
def test_section_revision_isolates_feedback_and_preflights_all_scopes(tmp_path: Path, blocker: str) -> None:
    """Revise every section with its own full feedback, or schedule no calls at all."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'section-revision.sqlite3')
    calls = []
    drafts = {}
    markers = ['UNIQUE_ALPHA_DRAFT', 'UNIQUE_BETA_DRAFT']

    async def stream(provider, model, system, messages, **kwargs):
        index = len(calls)
        section = (index // 2) % 2
        revision = index >= 4
        content = messages[0]['content']
        calls.append(content)
        assert markers[1 - section] not in content
        if index % 2 == 0:
            if revision:
                assert drafts[section] in content
                assert 'Produce a complete replacement draft' in content
            drafts[section] = f'{markers[section]} revision {int(revision)} explicit consent'
            yield drafts[section]
        else:
            yield json.dumps({'draft_hash': draft_hash(drafts[section]), 'criteria': [
                {'criterion_id': 'criterion-1', 'result': 'pass' if revision else 'fail',
                 'reason': 'Synthetic section review', 'evidence_quotes': ['explicit consent']}]})

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        response = client.post('/api/missions', json={'prompt': 'Draft and review each scope',
            'bulter_ids': [bot['id'] for bot in bots], 'sections': ['Issuance', 'Verification'],
            'review_criteria': ['Include consent']})
        assert response.status_code == 200
        original = wait_mission(client)
        assert original['status'] == 'completed_with_issues' and len(calls) == 4
        if blocker == 'last_section_budget':
            original['steps'][2]['output'] = 'x' * 24000
        elif blocker == 'section_history':
            original['steps'][3]['section_id'] = 'section-1'
        app.state.store.put('mission', original)
        response = client.post(f"/api/missions/{original['id']}/revise", json={})
        if blocker != 'none':
            assert response.status_code == (400 if blocker == 'last_section_budget' else 409)
            assert len(calls) == 4 and len(app.state.store.all('mission')) == 1
            return
        assert response.status_code == 200
        child = wait_mission(client)
        assert child['status'] == 'completed' and len(calls) == 8
        assert child['revision_round'] == 1 and len(child['section_budgets']) == 2
        assert len(child['section_revision_feedback']) == 2 and 'revision_feedback' not in child
        assert child['acceptance_status'] == 'not_assessed'
        for i in range(2):
            assert child['steps'][i * 2 + 1]['review']['draft_hash'] == draft_hash(drafts[i])
        assert app.state.store.get('mission', original['id']) == original
        assert client.post(f"/api/missions/{child['id']}/revise", json={}).status_code == 409
        assert client.get(f"/api/missions/{child['id']}/export/pptx").status_code == 400


@pytest.mark.parametrize('compose', [False, True])
def test_timing_prompt_uses_one_complete_mode_specific_example(compose: bool) -> None:
    """Composition must not teach the author an outline that omits flow geometry."""
    import json
    from src.app import timing_prompt, TimedPresentation
    prompt = timing_prompt('Use exactly 45 seconds of speaking and 15 seconds of discussion.', 60, True, compose)
    example = prompt.split('Return only JSON matching this structure: ', 1)[1].split('. Example values', 1)[0]
    outline = TimedPresentation.model_validate(json.loads(example))
    assert bool(outline.slides[0].flow_steps) == compose
    assert '45 seconds of speaking and 15 seconds of discussion' in prompt
    assert 'not the sample values' in prompt
    assert timing_prompt('Review the actual artifact.', 60, False, compose).count('matching this structure') == 0
    assert timing_prompt('No timed output requested.', None, True, compose) == 'No timed output requested.'


@pytest.mark.parametrize('output', ['PRIVATE_PAYLOAD_MARKER', '{"private_field":"PRIVATE_PAYLOAD_MARKER"}'])
def test_invalid_review_diagnostics_do_not_echo_payload(output: str) -> None:
    """Diagnostics may guide correction without duplicating untrusted or private text."""
    import json
    from src.app import validate_draft_review
    author = {'bulter_id': 'author', 'output': 'Synthetic draft', 'status': 'completed',
              'section_id': 'section-1', 'draft_revision': 1}
    result = validate_draft_review(output, author, ['Synthetic criterion'], 'reviewer')
    assert result['state'] == 'invalid' and result['error_code'] in {'review_json', 'review_schema'}
    assert 'PRIVATE_PAYLOAD_MARKER' not in json.dumps(result)


def test_review_schema_is_fresh_and_bound_to_requested_criteria() -> None:
    """A previous call cannot contaminate another mission's response constraints."""
    from src.app import review_response_schema
    first = review_response_schema(['One', 'Two'], 'a' * 64)
    second = review_response_schema(['Other'], 'b' * 64)
    assert first['properties']['draft_hash']['const'] == 'a' * 64
    assert second['properties']['draft_hash']['const'] == 'b' * 64
    assert first['properties']['criteria']['minItems'] == first['properties']['criteria']['maxItems'] == 2
    assert second['$defs']['CriterionReview']['properties']['criterion_id']['enum'] == ['criterion-1']
    assert first['additionalProperties'] is False
    assert first['$defs']['CriterionReview']['additionalProperties'] is False
