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

@pytest.mark.parametrize('count,total,expected', [(1, 60, 'pass'), (2, 60, 'invalid'), (1, 59, 'invalid'), (1, 61, 'invalid')])
def test_exact_presentation_constraints_include_discussion(count: int, total: int, expected: str) -> None:
    """Being within the budget does not satisfy an exact requested schedule."""
    import json
    from src.app import validate_timing
    check = validate_timing(json.dumps(timed_outline(45, 15)), 120,
                            expected_slide_count=count, exact_duration_seconds=total)
    assert check['state'] == expected
    assert check['total_seconds'] == 60 and check['overrun_seconds'] == 0
    assert check['expected_slide_count'] == count and check['exact_duration_seconds'] == total


@pytest.mark.parametrize('constraints', [
    {'expected_slide_count': True}, {'expected_slide_count': 0}, {'expected_slide_count': 61},
    {'exact_duration_seconds': '60'}, {'exact_duration_seconds': 121},
    {'expected_slide_count': 2, 'exact_duration_seconds': 1}])
def test_invalid_exact_constraints_reject_before_execution(constraints: dict) -> None:
    from src.app import MissionInput
    with pytest.raises(ValueError):
        MissionInput(prompt='Synthetic', bulter_ids=['a', 'b'], review_criteria=['Check'],
                     duration_budget_seconds=120, **constraints)
    with pytest.raises(ValueError):
        MissionInput(prompt='Synthetic', bulter_ids=['a', 'b'], expected_slide_count=1)


def test_exact_constraint_failure_overrides_model_pass_and_survives_revision(tmp_path: Path) -> None:
    """A within-budget but wrong schedule cannot pass; revisions retain the constraints."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'exact-schedule.sqlite3')
    draft = json.dumps(timed_outline(90, 0))
    calls = []
    async def stream(provider, model, system, messages, **kwargs):
        calls.append(messages[0]['content'])
        assert 'Required slide count: exactly 1' in calls[-1]
        assert 'Required total duration: exactly 60 seconds' in calls[-1]
        if len(calls) % 2:
            schema = kwargs['options']['response_schema']['properties']['slides']
            assert schema['minItems'] == schema['maxItems'] == 1
            yield draft
        else:
            yield json.dumps({'draft_hash': draft_hash(draft), 'criteria': [{'criterion_id': 'criterion-1',
                'result': 'pass', 'reason': 'Synthetic false positive', 'evidence_quotes': ['Explicit consent']}]})
    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        response = client.post('/api/missions', json={'prompt': 'Synthetic schedule',
            'bulter_ids': [b['id'] for b in bots], 'review_criteria': ['Consent'],
            'duration_budget_seconds': 120, 'expected_slide_count': 1, 'exact_duration_seconds': 60})
        assert response.status_code == 200
        mission = wait_mission(client)
        assert mission['status'] == 'completed_with_issues'
        assert mission['steps'][0]['timing_check']['constraint_mismatches'] == ['exact_duration']
        assert mission['steps'][1]['review']['state'] == 'needs_revision'
        assert client.get(f"/api/missions/{mission['id']}/export/pptx").status_code == 400
        assert client.post(f"/api/missions/{mission['id']}/revise", json={}).status_code == 200
        child = wait_mission(client)
        assert child['expected_slide_count'] == 1 and child['exact_duration_seconds'] == 60
        assert child['status'] == 'completed_with_issues' and child['acceptance_status'] == 'not_assessed'
        assert len(calls) == 4


@pytest.mark.parametrize('variant', ['bad_duration', 'extra_field', 'invalid_json', 'duplicate_field'])
def test_author_outline_errors_preserve_privacy_and_actionable_guidance(variant: str) -> None:
    """Parser diagnostics must not repeat model-controlled field values or keys."""
    import json
    from src.app import parse_presentation_outline
    outline = timed_outline(60, 0)
    if variant == 'bad_duration':
        outline['slides'][0]['duration_seconds'] = 'PRIVATE_PAYLOAD_MARKER'
    elif variant == 'extra_field':
        outline['PRIVATE_PAYLOAD_MARKER'] = 'sensitive test value'
    output = json.dumps(outline)
    if variant == 'invalid_json':
        output = 'PRIVATE_PAYLOAD_MARKER not JSON'
    elif variant == 'duplicate_field':
        output = '{"PRIVATE_PAYLOAD_MARKER":1,"PRIVATE_PAYLOAD_MARKER":2}'
    with pytest.raises(ValueError) as error:
        parse_presentation_outline(output)
    message = str(error.value)
    assert 'Author outline is invalid' in message and 'positive integer' in message
    assert 'PRIVATE_PAYLOAD_MARKER' not in message
    assert 'input_value' not in message and 'pydantic.dev' not in message


@pytest.mark.parametrize('quote', ['  explicit consent  ', '\texplicit consent\n', '\u00a0explicit consent\u00a0'])
def test_source_quotations_are_not_trimmed(quote: str) -> None:
    """Source references must match the submitted quotation, including edge whitespace."""
    import json
    from src.app import parse_presentation_outline, validate_sources
    outline = timed_outline(120, 30)
    outline['slides'][0]['claims'] = [{'text': 'Consent is required',
        'evidence': [{'source_id': 'source-1', 'quote': quote}]}]
    output = json.dumps(outline)
    assert parse_presentation_outline(output).slides[0].claims[0].evidence[0].quote == quote
    assert validate_sources(output, [], [{'id': 'source-1', 'content': quote}], True)['state'] == 'references_valid'
    assert validate_sources(output, [], [{'id': 'source-1', 'content': quote.strip()}], True)['state'] == 'invalid'


@pytest.mark.parametrize('quote', ['  explicit consent  ', '\texplicit consent\n', '\u00a0explicit consent\u00a0'])
def test_peer_quotations_are_not_trimmed(quote: str) -> None:
    """Peer evidence cannot pass after silently removing invented whitespace."""
    import json
    from src.app import draft_hash, validate_draft_review
    author = {'bulter_id': 'author', 'section_id': 'whole', 'draft_revision': 1, 'status': 'completed'}
    for text, expected in [(quote, 'criteria_pass'), (quote.strip(), 'invalid')]:
        author['output'] = text
        output = json.dumps({'draft_hash': draft_hash(text), 'criteria': [{'criterion_id': 'criterion-1',
            'result': 'pass', 'reason': 'Consent is present', 'evidence_quotes': [quote]}]})
        result = validate_draft_review(output, author, ['Require consent'], 'reviewer')
        assert result['state'] == expected
        if expected == 'criteria_pass':
            assert result['criteria'][0]['evidence_quotes'] == [quote]
        else:
            assert result['error_code'] == 'review_evidence'


@pytest.mark.parametrize('blank', [' ', '\t\n', '\u00a0'])
def test_untrimmed_source_quotes_still_reject_blank_evidence(blank: str) -> None:
    """Disabling quote normalization must not allow whitespace-only citations."""
    import json
    from src.app import validate_sources
    outline = timed_outline(120, 30)
    outline['slides'][0]['claims'] = [{'text': 'Consent is required',
        'evidence': [{'source_id': 'source-1', 'quote': blank}]}]
    assert validate_sources(json.dumps(outline), [], [{'id': 'source-1', 'content': blank}], True)['state'] == 'invalid'


@pytest.mark.parametrize('inexact', ['source', 'review'])
def test_inexact_quotation_blocks_mission_pass(tmp_path: Path, inexact: str) -> None:
    """A model pass cannot override quotation text absent from the retained evidence."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'quotation.sqlite3')
    outline = timed_outline(120, 30)
    claim = {'text': 'Consent is required', 'evidence': [{'source_id': '',
        'quote': '  explicit consent  ' if inexact == 'source' else 'explicit consent'}]}
    outline['slides'][0]['claims'] = [claim]
    calls = []

    async def stream(provider, model, system, messages, **kwargs):
        """Submit an inexact quote in either author citations or peer evidence."""
        calls.append(model)
        draft = json.dumps(outline)
        if len(calls) == 1:
            yield draft
        else:
            quote = '  Consent is required  ' if inexact == 'review' else 'Consent is required'
            yield json.dumps({'draft_hash': draft_hash(draft), 'criteria': [{'criterion_id': 'criterion-1',
                'result': 'pass', 'reason': 'Synthetic false positive', 'evidence_quotes': [quote]}]})

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        source = client.post('/api/attachments?filename=source.txt', content=b'Issuance requires explicit consent.').json()
        claim['evidence'][0]['source_id'] = source['id']
        response = client.post('/api/missions', json={'prompt': 'Prepare a sourced presentation',
            'bulter_ids': [bot['id'] for bot in bots], 'attachment_ids': [source['id']],
            'duration_budget_seconds': 1800, 'review_criteria': ['Use supported claims'], 'require_source_citations': True})
        assert response.status_code == 200
        mission = wait_mission(client)
        assert len(calls) == 2 and mission['status'] == 'completed_with_issues'
        review = mission['steps'][1]['review']
        if inexact == 'source':
            assert mission['steps'][0]['source_check']['state'] == 'invalid'
            assert review['blocking_checks'] == ['source_references']
            assert review['state'] == 'needs_revision'
        else:
            assert mission['steps'][0]['source_check']['state'] == 'references_valid'
            assert review['state'] == 'invalid' and review['error_code'] == 'review_evidence'
        assert mission['acceptance_status'] == 'not_assessed'
        assert client.get(f"/api/missions/{mission['id']}/export/pptx").status_code == 400


@pytest.mark.parametrize('second_path', ['/api/missions', '/api/missions/missing/resume', '/api/missions/missing/revise'])
def test_mission_preflight_reserves_execution_slot(tmp_path: Path, monkeypatch, second_path: str) -> None:
    """A request awaiting vision preflight must exclude concurrent starts and recovery."""
    import asyncio
    import httpx

    async def scenario() -> None:
        app = create_app(tmp_path / 'admission.sqlite3')
        entered, release = asyncio.Event(), asyncio.Event()
        checks = []

        async def vision(bots):
            checks.append(True)
            if len(checks) == 1:
                entered.set()
                await release.wait()

        async def stream(*args, **kwargs):
            await asyncio.Event().wait()
            yield ''

        monkeypatch.setattr('src.app.require_vision', vision)
        monkeypatch.setattr('src.app.generate', stream)
        app.state.store.put('attachment', {'id': 'photo', 'kind': 'image', 'text': '', 'image': '',
                                          'filename': 'synthetic.png', 'raw': ''})
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1',
                                         headers={'x-bulter-token': app.state.csrf}) as client:
                bot = (await client.post('/api/bulters', json={'name': 'Author', 'role': 'Draft',
                    'provider': 'ollama', 'model': 'synthetic'})).json()
                payload = {'prompt': 'Inspect the synthetic photo', 'bulter_ids': [bot['id']], 'attachment_ids': ['photo']}
                first = asyncio.create_task(client.post('/api/missions', json=payload))
                await asyncio.wait_for(entered.wait(), 2)
                try:
                    second = await asyncio.wait_for(client.post(second_path,
                        json=payload if second_path == '/api/missions' else {}), 2)
                finally:
                    release.set()
                    accepted = await first
                assert accepted.status_code == 200
                assert second.status_code == 409
                assert len(checks) == 1
                assert len(app.state.store.all('mission')) == 1

    asyncio.run(scenario())


def test_failed_preflight_releases_execution_reservation(tmp_path: Path, monkeypatch) -> None:
    """An invalid request must not leave the app permanently busy."""
    app = create_app(tmp_path / 'admission-release.sqlite3')

    async def stream(*args, **kwargs):
        yield 'Synthetic completed response'

    monkeypatch.setattr('src.app.generate', stream)
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bot = add_bot(client)
        assert client.post('/api/missions', json={'prompt': 'Invalid selection', 'bulter_ids': ['missing']}).status_code == 404
        assert client.post('/api/missions', json={'prompt': 'Valid selection', 'bulter_ids': [bot['id']]}).status_code == 200
        assert wait_mission(client)['status'] == 'completed'


@pytest.mark.parametrize('operation', ['credential_save', 'credential_remove', 'memory_sync', 'memory_import', 'bulter_remove'])
def test_preflight_blocks_mutations_that_require_idle_missions(tmp_path: Path, monkeypatch, operation: str) -> None:
    """An awaited preflight is busy for credential, import/sync and removal boundaries."""
    import asyncio
    import httpx
    from unittest.mock import Mock

    async def scenario() -> None:
        """Suspend a synthetic vision check and attempt one concurrent mutation."""
        app = create_app(tmp_path / 'mutation-preflight.sqlite3')
        entered, release = asyncio.Event(), asyncio.Event()
        save, remove = Mock(return_value={}), Mock(return_value={})
        monkeypatch.setattr(app.state.credentials, 'save', save)
        monkeypatch.setattr(app.state.credentials, 'remove', remove)

        async def vision(bots):
            """Hold preflight without querying an installed model."""
            entered.set()
            await release.wait()

        async def stream(*args, **kwargs):
            """Hold synthetic execution until lifespan shutdown cancels it."""
            await asyncio.Event().wait()
            yield ''

        monkeypatch.setattr('src.app.require_vision', vision)
        monkeypatch.setattr('src.app.generate', stream)
        app.state.store.put('attachment', {'id': 'photo', 'kind': 'image', 'text': '', 'image': '',
                                          'filename': 'synthetic.png', 'raw': ''})
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1',
                                         headers={'x-bulter-token': app.state.csrf}) as client:
                bot = (await client.post('/api/bulters', json={'name': 'Author', 'role': 'Draft',
                    'provider': 'ollama', 'model': 'synthetic'})).json()
                first = asyncio.create_task(client.post('/api/missions', json={'prompt': 'Inspect synthetic input',
                    'bulter_ids': [bot['id']], 'attachment_ids': ['photo']}))
                await asyncio.wait_for(entered.wait(), 2)
                try:
                    if operation == 'credential_save':
                        response = await client.put('/api/credentials/openai', json={'api_key': 'synthetic-test-value'})
                    elif operation == 'credential_remove':
                        response = await client.delete('/api/credentials/openai')
                    elif operation == 'memory_sync':
                        response = await client.post('/api/obsidian/sync')
                    elif operation == 'memory_import':
                        response = await client.post('/api/documents/missing/approve')
                    else:
                        response = await client.delete('/api/bulters/' + bot['id'])
                finally:
                    release.set()
                    started = await first
                assert started.status_code == 200 and response.status_code == 409
                save.assert_not_called()
                remove.assert_not_called()
                assert not app.state.store.get('bulter', bot['id']).get('removed_at')

    asyncio.run(scenario())


@pytest.mark.parametrize('second_id', ['slide-1', ' slide-1 '])
def test_duplicate_slide_identity_is_invalid_for_all_outline_consumers(second_id: str) -> None:
    """Source checks and composition parsing must enforce the timing check's identity rule."""
    import json
    from src.app import parse_presentation_outline, validate_sources, validate_timing
    slide = {'slide_id': 'slide-1', 'title': 'Consent', 'body': 'Consent is required',
             'speaker_notes': '', 'duration_seconds': 60,
             'claims': [{'text': 'Consent is required', 'evidence': [{'source_id': 's', 'quote': 'Consent'}]}]}
    output = json.dumps({'slides': [slide, {**slide, 'slide_id': second_id}], 'discussion_seconds': 0})
    with pytest.raises(ValueError, match='Author outline is invalid'):
        parse_presentation_outline(output)
    assert validate_timing(output, 120)['state'] == 'invalid'
    assert validate_sources(output, [], [{'id': 's', 'content': 'Consent'}], True)['state'] == 'invalid'


@pytest.mark.parametrize('count', [None, 3])
def test_composed_author_schema_uses_layout_limits_without_mutating_outline_schema(count: int | None) -> None:
    """Composition requests cannot advertise bounds larger than the layout supports."""
    from src.app import author_response_schema, TimedPresentation
    original = TimedPresentation.model_json_schema()
    composed = author_response_schema(True, count)
    properties = composed['$defs']['TimedSlide']['properties']
    assert properties['title']['maxLength'] == 90
    assert properties['body']['maxLength'] == 700
    assert properties['flow_steps']['items']['maxLength'] == 50
    assert composed['properties']['slides']['minItems'] == (count or 1)
    assert composed['properties']['slides']['maxItems'] == (count or 60)
    assert author_response_schema(False) == original
    assert TimedPresentation.model_json_schema() == original


@pytest.mark.parametrize('variant', ['pass', 'overrun', 'missing', 'duplicate', 'wrong_author', 'partial', 'invalid'])
def test_combined_section_timing_recomputes_complete_owned_drafts(variant: str) -> None:
    """Reject incomplete/misattributed scopes and ignore stale cached verdicts."""
    import json
    from src.app import validate_section_timing
    steps = [{'bulter_id': 'author', 'section_id': f'section-{i + 1}', 'status': 'completed',
              'output': json.dumps(timed_outline(30, 10)), 'timing_check': {'state': 'pass', 'total_seconds': 0}}
             for i in range(2)]
    if variant == 'overrun':
        steps[1]['output'] = json.dumps(timed_outline(51, 10))
    elif variant == 'missing':
        steps.pop()
    elif variant == 'duplicate':
        steps[1]['section_id'] = 'section-1'
    elif variant == 'wrong_author':
        steps[1]['bulter_id'] = 'reviewer'
    elif variant == 'partial':
        steps[1]['status'] = 'partial'
    elif variant == 'invalid':
        steps[1]['output'] = 'Not a timed outline'
    mission = {'duration_budget_seconds': 100, 'team': [{'id': 'author'}, {'id': 'reviewer'}],
               'sections': ['Issue', 'Present'], 'steps': steps}
    check = validate_section_timing(mission)
    assert check['state'] == ('pass' if variant == 'pass' else 'exceeded' if variant == 'overrun' else 'invalid')
    if variant in {'pass', 'overrun'}:
        assert check['total_seconds'] == (80 if variant == 'pass' else 101)
        assert check['discussion_seconds'] == 20 and check['slide_count'] == 2
    else:
        assert 'total_seconds' not in check


@pytest.mark.parametrize('recovery', [False, True])
@pytest.mark.parametrize('exact', [False, True])
@pytest.mark.parametrize('template', [False, True])
def test_section_timing_overrun_revision_and_recovery(tmp_path: Path, recovery: bool, exact: bool, template: bool) -> None:
    """Individual passes cannot hide aggregate overrun; explicit revision can fix it."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'combined-timing.sqlite3')
    calls = []
    drafts = {}
    phase = {'revision': False, 'fail_once': recovery}

    async def stream(provider, model, system, messages, **kwargs):
        """Return section-local drafts/reviews with a resumable interruption."""
        content = messages[0]['content']
        calls.append(content)
        scope = 'Issue' if 'CURRENT SECTION ONLY:\nIssue' in content else 'Present'
        is_reviewer = 'draft_hash' in kwargs.get('options', {}).get('response_schema', {}).get('properties', {})
        if scope == 'Present' and phase['fail_once']:
            phase['fail_once'] = False
            raise ProviderError('Synthetic interruption')
        if not is_reviewer:
            assert 'budget is shared by ALL sections' in content
            assert 'Section inspection layout:' in content
            assert 'Never invent image IDs or remote image URLs.' in content
            assert 'inspection-only' in content
            layout_fields = kwargs['options']['response_schema']['$defs']['TimedSlide']['properties']
            assert layout_fields['title']['maxLength'] == 90
            assert layout_fields['body']['maxLength'] == 700
            assert layout_fields['flow_steps']['items']['maxLength'] == 50
            if exact:
                assert 'Required slide count across all 2 sections combined: exactly 2.' in content
                assert 'Required total duration across all 2 sections combined: exactly 100 seconds' in content
                assert kwargs['options']['response_schema']['properties']['slides']['minItems'] == 1
                assert kwargs['options']['response_schema']['properties']['slides']['maxItems'] == 1
                assert 'THIS SECTION ONLY: exactly 1 slides.' in content
            if phase['revision']:
                assert 'combined_section_timing' in content and '"total_seconds": 140' in content
            drafts[scope] = json.dumps(timed_outline(40 if phase['revision'] else 60, 10))
            yield drafts[scope]
        else:
            yield json.dumps({'draft_hash': draft_hash(drafts[scope]), 'criteria': [
                {'criterion_id': 'criterion-1', 'result': 'pass', 'reason': 'Contains consent',
                 'evidence_quotes': ['Explicit consent']}]})

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        template_options = {}
        if template:
            from src.tests.test_attachments import office
            upload = client.post('/api/attachments?filename=design.pptx', content=office('pptx', 'Synthetic template'))
            assert upload.status_code == 200
            template_options = {'attachment_ids': [upload.json()['id']], 'template_id': upload.json()['id']}
        response = client.post('/api/missions', json={**template_options, 'prompt': 'Draft wallet sections',
            'bulter_ids': [bot['id'] for bot in bots], 'sections': ['Issue', 'Present'],
            'review_criteria': ['Include consent'], 'duration_budget_seconds': 100,
            **({'expected_slide_count': 2, 'exact_duration_seconds': 100, 'section_slide_counts': [1, 1]} if exact else {})})
        assert response.status_code == 200
        original = wait_mission(client)
        if recovery:
            assert original['status'] == 'failed' and original['section_timing_check']['state'] == 'invalid'
            response = client.post(f"/api/missions/{original['id']}/resume", json={})
            assert response.status_code == 200
            original = wait_mission(client)
            assert len(calls) == 5  # One failed call, with the completed first pair reused.
        assert original['status'] == 'completed_with_issues'
        assert original['section_timing_check']['total_seconds'] == 140
        assert original['section_timing_check']['state'] == ('invalid' if exact else 'exceeded')
        assert all(step['review_state'] == 'criteria_pass' for step in original['steps'][1::2])
        phase['revision'] = True
        response = client.post(f"/api/missions/{original['id']}/revise", json={})
        assert response.status_code == 200
        child = wait_mission(client)
        assert child['status'] == 'completed' and child['section_timing_check']['total_seconds'] == 100
        assert child['section_timing_check']['state'] == 'pass'
        assert child['acceptance_status'] == 'not_assessed'
        assembled = client.get(f"/api/missions/{child['id']}/outline")
        assert assembled.status_code == 200 and assembled.headers['cache-control'] == 'no-store'
        import hashlib
        assert assembled.headers['x-outline-sha256'] == hashlib.sha256(assembled.content).hexdigest()
        payload = assembled.json()
        assert len(payload['manifest']['slides']) == 2 and payload['artifact_review_status'] == 'not_assessed'
        assert [slide['slide_id'] for slide in payload['manifest']['slides']] == ['section-1-slide-1', 'section-2-slide-1']
        assert client.get(f"/api/missions/{child['id']}/outline").content == assembled.content
        if template:
            assert client.get(f"/api/missions/{child['id']}/outline/pptx").status_code == 200
        assert client.get(f"/api/missions/{original['id']}/outline").status_code == 409
        assert client.get(f"/api/missions/{child['id']}/export/pptx").status_code == 400
        assert app.state.store.get('mission', original['id']) == original


@pytest.mark.parametrize('unsupported', [{'compose_presentation': True}])
def test_timed_sections_reject_unimplemented_whole_artifact_targets(unsupported: dict) -> None:
    """Do not apply whole-deck targets separately to each section or claim assembly."""
    from pydantic import ValidationError
    from src.app import MissionInput
    with pytest.raises(ValidationError, match='artifact assembly'):
        MissionInput(prompt='Wallet', bulter_ids=['a', 'b'], sections=['Issue', 'Present'],
                     review_criteria=['Consent'], duration_budget_seconds=100, **unsupported)


@pytest.mark.parametrize('count,duration,state,mismatches', [
    (2, 80, 'pass', []), (3, 80, 'invalid', ['slide_count']),
    (2, 81, 'invalid', ['exact_duration']), (3, 81, 'invalid', ['slide_count', 'exact_duration']),
])
def test_exact_targets_apply_to_combined_sections(count: int, duration: int, state: str, mismatches: list[str]) -> None:
    """Exact targets validate the aggregate, never each individual section."""
    import json
    from src.app import validate_section_timing
    mission = {'duration_budget_seconds': 100, 'expected_slide_count': count, 'exact_duration_seconds': duration,
        'team': [{'id': 'author'}, {'id': 'reviewer'}], 'sections': ['Issue', 'Present'],
        'steps': [{'bulter_id': 'author', 'section_id': f'section-{i + 1}', 'status': 'completed',
                   'output': json.dumps(timed_outline(30, 10))} for i in range(2)]}
    result = validate_section_timing(mission)
    assert result['state'] == state and result['total_seconds'] == 80
    assert result.get('constraint_mismatches', []) == mismatches
    assert result['expected_slide_count'] == count and result['exact_duration_seconds'] == duration
    assert all(item['state'] == 'pass' and 'expected_slide_count' not in item for item in result['sections'])


@pytest.mark.parametrize('targets,message', [
    ({'expected_slide_count': 1}, 'at least one slide per section'),
    ({'exact_duration_seconds': 1}, 'at least one second per section'),
])
def test_impossible_section_targets_rejected_before_inference(targets: dict, message: str) -> None:
    """Each nonempty section needs a slide with at least one declared second."""
    from pydantic import ValidationError
    from src.app import MissionInput
    with pytest.raises(ValidationError, match=message):
        MissionInput(prompt='Wallet', bulter_ids=['a', 'b'], sections=['Issue', 'Present'],
                     review_criteria=['Consent'], duration_budget_seconds=100, **targets)


@pytest.mark.parametrize('variant', ['valid', 'stale_review', 'wrong_reviewer', 'scope_swap', 'partial', 'timing', 'too_many', 'sources', 'valid_sources'])
def test_combined_outline_preserves_provenance_and_rechecks_gates(variant: str) -> None:
    """Assembly cannot trust cached passes or lose content behind duplicate local IDs."""
    import copy
    import json
    from src.app import assemble_section_outline, draft_hash
    mission = {'id': 'test', 'status': 'completed', 'sections': ['Issue', 'Present'],
        'team': [{'id': 'a'}, {'id': 'b'}], 'duration_budget_seconds': 1000,
        'review_criteria': ['Consent'], 'steps': [], 'section_timing_check': {'state': 'pass'}}
    for index in range(2):
        outline = timed_outline(30, 10)
        outline['slides'][0]['speaker_notes'] = f'Notes for section {index + 1}'
        if variant == 'too_many':
            outline['slides'] = [{**outline['slides'][0], 'slide_id': str(i), 'duration_seconds': 1} for i in range(31)]
        if variant in {'sources', 'valid_sources'}:
            mission.update(require_source_citations=True, connector_evidence=[{'id': 'src', 'content': 'Explicit consent'}])
            outline['slides'][0]['claims'] = [{'text': 'Consent', 'evidence': [{'source_id': 'src', 'quote': 'Explicit consent' if variant == 'valid_sources' else 'Invented'}]}]
        output = json.dumps(outline)
        author = {'bulter_id': 'a', 'section_id': f'section-{index + 1}', 'draft_revision': 1,
                  'status': 'completed', 'output': output}
        reviewer = {'bulter_id': 'b', 'section_id': author['section_id'], 'status': 'completed',
            'review_state': 'criteria_pass', 'output': json.dumps({'draft_hash': draft_hash(output), 'criteria': [
                {'criterion_id': 'criterion-1', 'result': 'pass', 'reason': 'Synthetic', 'evidence_quotes': ['Explicit consent']}]})}
        mission['steps'].extend([author, reviewer])
    if variant == 'stale_review':
        mission['steps'][0]['output'] += ' '
    elif variant == 'wrong_reviewer':
        mission['steps'][1]['bulter_id'] = 'a'
    elif variant == 'scope_swap':
        mission['steps'][1]['section_id'] = 'section-2'
    elif variant == 'partial':
        mission['steps'][0]['status'] = 'partial'
    elif variant == 'timing':
        mission['duration_budget_seconds'] = 60
    before = copy.deepcopy(mission)
    if variant not in {'valid', 'valid_sources'}:
        with pytest.raises(ValueError):
            assemble_section_outline(mission)
    else:
        result = assemble_section_outline(mission)
        assert result['manifest']['discussion_seconds'] == 20
        assert result['manifest']['slides'][1]['speaker_notes'] == 'Notes for section 2'
        assert result['sections'][1]['slides'] == [{'source_slide_id': 'slide-1', 'assembled_slide_id': 'section-2-slide-1'}]
        assert result['sections'][0]['draft_hash'] == draft_hash(mission['steps'][0]['output'])
        assert result['acceptance_status'] == result['artifact_review_status'] == 'not_assessed'
    assert mission == before


def test_section_template_rejects_word_before_model_calls(tmp_path: Path) -> None:
    """A section inspection template must be a compatible PPTX, never a DOCX."""
    from src.tests.test_attachments import office
    app = create_app(tmp_path / 'section-template.sqlite3')
    with TestClient(app) as client, patch('src.app.generate') as generate:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        uploaded = client.post('/api/attachments?filename=design.docx', content=office('docx', 'Template'))
        identifier = uploaded.json()['id']
        response = client.post('/api/missions', json={'prompt': 'Wallet', 'bulter_ids': [bot['id'] for bot in bots],
            'sections': ['Issue', 'Present'], 'review_criteria': ['Consent'], 'duration_budget_seconds': 120,
            'attachment_ids': [identifier], 'template_id': identifier})
        assert response.status_code == 400 and 'PPTX' in response.json()['detail']
        generate.assert_not_called()
        assert app.state.store.all('mission') == []


@pytest.mark.parametrize('budget,author,sections,expected', [
    (120, True, 2, True), (None, True, 2, False),
    (120, False, 2, False), (120, True, 0, False)])
def test_section_layout_guidance_is_scoped_to_timed_authors(budget, author: bool, sections: int, expected: bool) -> None:
    """Preflight and execution share visual guidance without changing ordinary outlines."""
    from src.app import timing_prompt
    prompt = timing_prompt('Wallet', budget, author, section_count=sections)
    assert ('Section inspection layout:' in prompt) is expected
    if expected:
        assert '"flow_steps": ["First step", "Second step"]' in prompt
        assert 'image_id only from selected image attachments' in prompt
        assert 'do not combine a picture and flow_steps on one slide' in prompt
        assert 'outline peer review does not establish artifact or visual acceptance' in prompt


@pytest.mark.parametrize('fault', ['title', 'panel_body', 'flow_label', 'unknown_image', 'line_breaks'])
def test_section_layout_failure_blocks_peer_pass_and_revises(tmp_path: Path, fault: str) -> None:
    """Unrenderable sections remain revisable even when their model reviewer passes."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'layout-check.sqlite3')
    state = {'revision': False, 'draft': ''}

    async def stream(provider, model, system, messages, **kwargs):
        content = messages[0]['content']
        reviewer = 'draft_hash' in kwargs['options']['response_schema']['properties']
        if reviewer:
            assert 'SECTION LAYOUT CHECK' in content
            yield json.dumps({'draft_hash': draft_hash(state['draft']), 'criteria': [
                {'criterion_id': 'criterion-1', 'result': 'pass', 'reason': 'Consent is present',
                 'evidence_quotes': ['Explicit consent']}]})
        else:
            if state['revision']:
                assert '"layout_check"' in content and 'Section cannot use the inspection layout' in content
            outline = timed_outline(60, 0)
            if not state['revision']:
                slide = outline['slides'][0]
                if fault == 'title':
                    slide['title'] = 'x' * 91
                elif fault == 'panel_body':
                    slide.update(body='Explicit consent ' + 'x' * 410, flow_steps=['Consent', 'Issue'])
                elif fault == 'flow_label':
                    slide['flow_steps'] = ['Consent', 'x' * 51]
                elif fault == 'unknown_image':
                    slide.update(image_id='not-selected', image_caption='Example')
                else:
                    slide['title'] = 'Title\n' * 10
            state['draft'] = json.dumps(outline)
            yield state['draft']

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        response = client.post('/api/missions', json={'prompt': 'Wallet', 'bulter_ids': [b['id'] for b in bots],
            'sections': ['Consent'], 'review_criteria': ['Consent'], 'duration_budget_seconds': 120})
        assert response.status_code == 200
        parent = wait_mission(client)
        assert parent['status'] == 'completed_with_issues'
        assert parent['steps'][0]['layout_check']['state'] == 'invalid'
        assert parent['steps'][1]['review']['state'] == 'needs_revision'
        assert 'section_layout' in parent['steps'][1]['review']['blocking_checks']
        assert client.get(f"/api/missions/{parent['id']}/outline/pptx").status_code == 409
        assert not app.state.store.all('artifact') and not app.state.store.all('section_draft')
        state['revision'] = True
        assert client.post(f"/api/missions/{parent['id']}/revise", json={}).status_code == 200
        child = wait_mission(client)
        assert child['status'] == 'completed'
        assert child['steps'][0]['layout_check']['state'] == 'pass'
        assert child['acceptance_status'] == 'not_assessed'
        assert client.get(f"/api/missions/{child['id']}/outline/pptx").status_code == 200
        assert app.state.store.get('mission', parent['id']) == parent


@pytest.mark.parametrize('variant', ['pass', 'wrong_hash', 'provider_failure', 'output_limit', 'cancel', 'cloud', 'changed_bot', 'changed_source', 'context', 'revoked_memory', 'attempt_limit', 'export_hash', 'export_projection', 'export_identity', 'export_partial', 'export_missing', 'export_criteria', 'export_raw_review', 'export_bytes'])
def test_section_artifact_reviews_bind_two_local_assessments(tmp_path: Path, variant: str) -> None:
    """Two independent reviews bind to retained bytes without promoting acceptance."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'section-reviews.sqlite3', vault=tmp_path / 'empty')
    calls = []
    import asyncio
    import threading
    entered = threading.Event()
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        output = json.dumps(timed_outline(60, 0))
        parent = {'id': 'source', 'status': 'completed', 'prompt': 'Review consent', 'sections': ['Consent'],
            'team': bots, 'cloud': False, 'duration_budget_seconds': 120, 'attachments': [],
            'review_criteria': ['Consent'], 'acceptance_status': 'not_assessed', 'source_revisions': {}, 'steps': [
                {'bulter_id': bots[0]['id'], 'section_id': 'section-1', 'draft_revision': 1, 'status': 'completed', 'output': output},
                {'bulter_id': bots[1]['id'], 'section_id': 'section-1', 'status': 'completed', 'output': json.dumps({
                    'draft_hash': draft_hash(output), 'criteria': [{'criterion_id': 'criterion-1', 'result': 'pass',
                    'reason': 'Consent', 'evidence_quotes': ['Explicit consent']}]})}]}
        if variant == 'cloud':
            parent['team'] = [{**b, 'provider': 'openai'} for b in bots]
        elif variant == 'changed_bot':
            app.state.store.put('bulter', {**bots[0], 'name': 'Changed'})
        elif variant == 'changed_source':
            parent['source_revisions'] = {'connector_evidence': {'missing': 'old'}}
        elif variant == 'context':
            parent['prompt'] = 'Long brief ' * 4000
        elif variant == 'revoked_memory':
            parent['required_memory_revisions'] = {'missing': 'old'}
        elif variant == 'attempt_limit':
            for i in range(3):
                app.state.store.put('mission', {'id': str(i), 'status': 'completed', 'section_source_mission_id': 'source'})
        app.state.store.put('mission', parent)

        async def stream(provider, model, system, messages, **kwargs):
            calls.append(messages[0]['content'])
            assert provider == 'ollama' and 'api_key' not in kwargs
            assert 'application-section-assembly' not in messages[0]['content']
            if variant == 'cancel':
                entered.set()
                await asyncio.Event().wait()
            if variant == 'output_limit':
                yield 'x' * 17000
                return
            if variant == 'provider_failure':
                raise ProviderError('Synthetic provider failure')
            digest = kwargs['options']['response_schema']['properties']['draft_hash']['const']
            yield json.dumps({'draft_hash': '0' * 64 if variant == 'wrong_hash' else digest,
                'criteria': [{'criterion_id': 'criterion-1', 'result': 'pass', 'reason': 'Independent review',
                              'evidence_quotes': ['Explicit consent']}]})

        with patch('src.app.generate', stream):
            response = client.post('/api/missions/source/review-section-artifact')
            if variant in {'cloud', 'changed_bot', 'changed_source', 'context', 'revoked_memory', 'attempt_limit'}:
                assert response.status_code in {400, 409}
                assert not calls and len(app.state.store.all('mission')) == (4 if variant == 'attempt_limit' else 1)
                return
            assert response.status_code == 200, response.text
            if variant == 'cancel':
                assert entered.wait(2)
                assert client.post('/api/missions/' + response.json()['id'] + '/stop').status_code == 200
            result = wait_mission(client)
        assert result['status'] == {'wrong_hash': 'completed_with_issues', 'provider_failure': 'failed', 'output_limit': 'failed', 'cancel': 'cancelled'}.get(variant, 'completed')
        assert result['acceptance_status'] == 'not_assessed'
        assert result['section_source_mission_id'] == 'source'
        assert app.state.store.get('mission', 'source') == parent
        download = client.get(f"/api/missions/{result['id']}/export/pptx")
        assert download.status_code == (200 if result['status'] == 'completed' else 400)
        if result['status'] == 'completed':
            assert download.content == client.get('/api/missions/source/outline/pptx').content
            assert download.headers['x-artifact-sha256'] == result['section_artifact_sha256']
            assert download.headers['cache-control'] == 'no-store'
            assert 'user-acceptance-not-assessed' in download.headers['x-artifact-purpose']
            assert client.get(f"/api/missions/{result['id']}/export/docx").status_code == 400
            assert client.get(f"/api/missions/{result['id']}/export/pptx?use_template=true").status_code == 400
        if variant not in {'provider_failure', 'output_limit', 'cancel'}:
            assert len(calls) == 2 and all('Independent review' not in content for content in calls)
            assert {s['review']['reviewer_id'] for s in result['steps']} == {b['id'] for b in bots}
            assert all(s['review']['artifact_sha256'] == result['section_artifact_sha256'] for s in result['steps'])
            assert result['review_text_sha256'] == client.get('/api/missions/source/outline/review-text').json()['review_text_sha256']

        if variant.startswith('export_'):
            if variant == 'export_hash':
                result['section_artifact_sha256'] = '0' * 64
            elif variant == 'export_projection':
                result['review_text_sha256'] = '0' * 64
            elif variant == 'export_identity':
                result['steps'][1]['bulter_id'] = bots[0]['id']
            elif variant == 'export_partial':
                result['steps'][0]['status'] = 'partial'
            elif variant == 'export_missing':
                result['steps'].pop()
            elif variant == 'export_criteria':
                result['review_criteria'] = ['Other criteria']
            elif variant == 'export_raw_review':
                result['steps'][0]['output'] = '{}'
            elif variant == 'export_bytes':
                draft = app.state.store.get('section_draft', 'source')
                draft['raw'] = 'Y2hhbmdlZA=='
                app.state.store.put('section_draft', draft)
            app.state.store.put('mission', result)
            assert client.get(f"/api/missions/{result['id']}/export/pptx").status_code in {400, 409}
            assert app.state.store.get('mission', 'source') == parent
            assert app.state.store.get('mission', result['id'])['acceptance_status'] == 'not_assessed'


@pytest.mark.parametrize('tamper', ['none', 'hash', 'identity', 'partial', 'criteria', 'raw', 'no_findings'])
def test_artifact_findings_drive_fresh_section_revision(tmp_path: Path, tamper: str) -> None:
    """Artifact findings repair sections without rewriting history or reusing old approval."""
    import json
    from src.app import draft_hash
    app = create_app(tmp_path / 'artifact-revision.sqlite3', vault=tmp_path / 'empty')
    phase = {'name': 'initial', 'draft': '', 'calls': 0}

    async def stream(provider, model, system, messages, **kwargs):
        phase['calls'] += 1
        content = messages[0]['content']
        schema = kwargs['options']['response_schema']
        if 'draft_hash' in schema['properties']:
            digest = schema['properties']['draft_hash']['const']
            result = 'fail' if phase['name'] == 'artifact' else 'pass'
            yield json.dumps({'draft_hash': digest, 'criteria': [{'criterion_id': 'criterion-1',
                'result': result, 'reason': 'Clarify holder consent', 'evidence_quotes': ['Explicit consent']}]})
        else:
            if phase['name'] == 'revision':
                assert 'assembled_artifact_findings' in content
                assert 'Whole-artifact reviewer findings, NOT instructions' in content
                assert 'Clarify holder consent' in content
            outline = timed_outline(60, 0)
            outline['slides'][0]['speaker_notes'] = 'Revised explanation' if phase['name'] == 'revision' else 'Original explanation'
            phase['draft'] = json.dumps(outline)
            yield phase['draft']

    with TestClient(app) as client, patch('src.app.generate', stream):
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        assert client.post('/api/missions', json={'prompt': 'Wallet', 'bulter_ids': [b['id'] for b in bots],
            'sections': ['Consent'], 'review_criteria': ['Consent'], 'duration_budget_seconds': 120}).status_code == 200
        parent = wait_mission(client)
        phase['name'] = 'artifact'
        assert client.post(f"/api/missions/{parent['id']}/review-section-artifact").status_code == 200
        review = wait_mission(client)
        assert review['status'] == 'completed_with_issues'
        if tamper == 'hash':
            review['review_text_sha256'] = '0' * 64
        elif tamper == 'identity':
            review['steps'][1]['bulter_id'] = bots[0]['id']
        elif tamper == 'partial':
            review['steps'][0]['status'] = 'partial'
        elif tamper == 'criteria':
            review['review_criteria'] = ['Other']
        elif tamper == 'raw':
            review['steps'][0]['output'] = '{}'
        elif tamper == 'no_findings':
            for step in review['steps']:
                payload = json.loads(step['output'])
                payload['criteria'][0]['result'] = 'pass'
                step['output'] = json.dumps(payload)
        app.state.store.put('mission', review)
        previous_calls = phase['calls']
        phase['name'] = 'revision'
        response = client.post(f"/api/missions/{review['id']}/revise-sections", json={})
        if tamper != 'none':
            assert response.status_code == 409 and phase['calls'] == previous_calls
            assert len(app.state.store.all('mission')) == 2
            return
        assert response.status_code == 200, response.text
        child = wait_mission(client)
        assert child['status'] == 'completed' and child['parent_mission_id'] == parent['id']
        assert child['revision_round'] == 1 and child['acceptance_status'] == 'not_assessed'
        assert child['section_revision_feedback'][0]['assembled_artifact_findings']['review_mission_id'] == review['id']
        assert app.state.store.get('mission', parent['id']) == parent
        assert app.state.store.get('mission', review['id']) == review
        assert client.post(f"/api/missions/{review['id']}/revise-sections", json={}).status_code == 409
        assert client.get(f"/api/missions/{child['id']}/export/pptx").status_code == 400
        phase['name'] = 'final_review'
        assert client.post(f"/api/missions/{child['id']}/review-section-artifact").status_code == 200
        final = wait_mission(client)
        assert final['status'] == 'completed'
        assert final['section_artifact_sha256'] != review['section_artifact_sha256']
        assert client.get(f"/api/missions/{final['id']}/export/pptx").status_code == 200
        assert client.get(f"/api/missions/{review['id']}/export/pptx").status_code == 400


@pytest.mark.parametrize('mode', ['sections', 'composition', 'design_only', 'reference'])
def test_composition_design_is_not_research_evidence(tmp_path: Path, mode: str) -> None:
    """Truncated design samples cannot crowd out or masquerade as research sources."""
    import json
    from src.tests.test_attachments import office
    from src.app import draft_hash, revision_hash
    app = create_app(tmp_path / 'design-scope.sqlite3', vault=tmp_path / 'empty')
    calls = []
    with TestClient(app) as client:
        client.headers['x-bulter-token'] = app.state.csrf
        bots = [add_bot(client, 'Author'), add_bot(client, 'Reviewer')]
        uploaded = client.post('/api/attachments?filename=design.pptx', content=office('pptx', 'Private sample marker'))
        assert uploaded.status_code == 200
        template_id = uploaded.json()['id']
        record = app.state.store.get('attachment', template_id)
        record.update(text='Private sample marker ' * 700, truncated=True)
        app.state.store.put('attachment', record)
        app.state.store.put('connector_evidence', {'id': 'research', 'content': 'Explicit consent',
            'title': 'Synthetic official research', 'source': 'web', 'local_only': True, 'truncated': False})

        async def stream(provider, model, system, messages, **kwargs):
            content = messages[0]['content']
            calls.append(content)
            assert 'Private sample marker' not in content
            assert 'design_only' in content
            schema = kwargs['options']['response_schema']
            if 'draft_hash' in schema['properties']:
                yield json.dumps({'draft_hash': schema['properties']['draft_hash']['const'], 'criteria': [
                    {'criterion_id': 'criterion-1', 'result': 'pass', 'reason': 'Consent', 'evidence_quotes': ['Explicit consent']}]})
            else:
                assert schema['$defs']['TimedSlide']['properties']['claims']['minItems'] == 1
                assert 'claims' in schema['$defs']['TimedSlide']['required']
                assert schema['$defs']['ClaimEvidence']['properties']['source_id']['enum'] == ['research']
                outline = timed_outline(60, 0)
                outline['slides'][0].update(flow_steps=['Consent', 'Issue'], claims=[{'text': 'Consent',
                    'evidence': [{'source_id': 'research', 'quote': 'Explicit consent'}]}])
                yield json.dumps(outline)

        with patch('src.app.generate', stream):
            options = {'sections': ['Consent']} if mode in {'sections', 'design_only'} else {'compose_presentation': True}
            if mode == 'reference':
                options = {}
            response = client.post('/api/missions', json={'prompt': 'Wallet', 'bulter_ids': [b['id'] for b in bots],
                'attachment_ids': [template_id], **({'template_id': template_id} if mode != 'reference' else {}),
                'evidence_ids': [] if mode == 'design_only' else ['research'],
                'review_criteria': ['Consent'], 'duration_budget_seconds': 120, 'require_source_citations': True, **options})
            if mode in {'design_only', 'reference'}:
                assert response.status_code == 400 and not calls
                return
            assert response.status_code == 200, response.text
            mission = wait_mission(client)
        assert mission['status'] == 'completed'
        assert mission['attachments'][0]['text'] == ''
        assert mission['source_register'][0]['source_id'] == 'research' and len(mission['source_register']) == 1
        assert mission['source_revisions']['attachment'][template_id] == revision_hash(record)
        assert app.state.store.get('attachment', template_id) == record
        assert mission['steps'][0]['source_check']['state'] == 'references_valid'
        if mode == 'sections':
            assert client.get(f"/api/missions/{mission['id']}/outline/pptx").status_code == 200
        else:
            assert client.get(f"/api/missions/{mission['id']}/export/pptx").status_code == 200


@pytest.mark.parametrize('source_ids', [None, [], ['first'], ['first', 'second', 'first']])
def test_local_author_citation_schema_requires_registered_sources(source_ids) -> None:
    """Required evidence cannot be omitted in local structured author output."""
    from src.app import author_response_schema, TimedPresentation
    if source_ids == []:
        with pytest.raises(ValueError, match='registered source'):
            author_response_schema(True, source_ids=source_ids)
        return
    schema = author_response_schema(True, source_ids=source_ids)
    slide = schema['$defs']['TimedSlide']
    if source_ids is None:
        assert 'claims' not in slide['required']
        assert 'enum' not in schema['$defs']['ClaimEvidence']['properties']['source_id']
    else:
        assert slide['properties']['claims']['minItems'] == 1
        assert 'claims' in slide['required']
        assert schema['$defs']['ClaimEvidence']['properties']['source_id']['enum'] == list(dict.fromkeys(source_ids))
    assert 'claims' not in TimedPresentation.model_json_schema()['$defs']['TimedSlide']['required']


@pytest.mark.parametrize('overrides', [
    {'sections': []}, {'duration_budget_seconds': None}, {'expected_slide_count': None},
    {'section_slide_counts': [4]}, {'section_slide_counts': [1, 2]},
    {'section_slide_counts': [0, 4]}, {'section_slide_counts': [True, 3]},
    {'section_slide_counts': ['1', 3]}, {'section_slide_counts': [61, 1]},
])
def test_invalid_explicit_section_allocation_rejected(overrides: dict) -> None:
    """Reject ambiguous allocations before any generation is scheduled."""
    from pydantic import ValidationError
    from src.app import MissionInput
    data = dict(prompt='Wallet', bulter_ids=['a', 'b'], sections=['Issue', 'Present'],
                review_criteria=['Consent'], duration_budget_seconds=100,
                expected_slide_count=4, section_slide_counts=[1, 3])
    with pytest.raises(ValidationError):
        MissionInput(**{**data, **overrides})


@pytest.mark.parametrize('actual', [[1, 3], [2, 2], [3, 1]])
def test_section_allocation_rechecks_distribution_despite_matching_total(actual: list[int]) -> None:
    """Four total slides cannot conceal a wrong section allocation."""
    import json
    from src.app import MissionInput, validate_section_timing
    request = MissionInput(prompt='Wallet', bulter_ids=['a', 'b'], sections=['Issue', 'Present'],
                           review_criteria=['Consent'], duration_budget_seconds=100,
                           expected_slide_count=4, section_slide_counts=[1, 3])
    mission = request.model_dump()
    mission['team'] = [{'id': 'a'}, {'id': 'b'}]
    mission['steps'] = []
    for index, count in enumerate(actual):
        outline = timed_outline(10, 0)
        outline['slides'] = [{**outline['slides'][0], 'slide_id': f'slide-{i}'} for i in range(count)]
        mission['steps'].append({'bulter_id': 'a', 'section_id': f'section-{index + 1}',
                                 'status': 'completed', 'output': json.dumps(outline),
                                 'timing_check': {'state': 'pass'}})
    result = validate_section_timing(mission)
    assert result['state'] == ('pass' if actual == [1, 3] else 'invalid')
    assert [item['expected_slide_count'] for item in result['sections']] == [1, 3]
