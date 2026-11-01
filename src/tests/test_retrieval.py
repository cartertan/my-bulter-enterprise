"""Test bounded local retrieval with synthetic notes. Author: Carter Tan.

Inputs: Synthetic memories. Outputs: policy and context assertions.
Assumptions: No providers or personal files are accessed.
"""
import pytest
from src.app import select_memory, build_context
from src.providers import ProviderError

BOT = {"id": "a", "name": "Test", "role": "Review", "instructions": "", "shared_memory": True}


def note(identifier: str, text: str, **extra) -> dict:
    """Create a synthetic approved local memory."""
    return {"id": identifier, "title": identifier, "content": text, "active": True,
            "owner_id": None, "cloud_allowed": False, **extra}


def test_relevance_and_budget() -> None:
    """Large collections fit without losing the task or truncating notes."""
    memories = [note(str(i), "certificate " * 240) for i in range(90)]
    memories += [note("target", "Zebra migration decision"), note("other", "unrelated sports")]
    selected = select_memory(memories, BOT, False, "Zebra certificate migration", [])
    assert selected[0]["id"] == "target"
    assert 1 < len(selected) < len(memories)
    assert "other" not in [m["id"] for m in selected]
    system, messages = build_context(BOT, selected, "Zebra certificate migration", [])
    assert len(system) + len(messages[0]["content"]) <= 24000
    assert all(m in memories for m in selected)


def test_policy_before_ranking() -> None:
    """Relevance cannot override cloud restrictions or private ownership."""
    memories = [note("local", "zebra"), note("private", "zebra", owner_id="b", cloud_allowed=True),
                note("inactive", "zebra", active=False, cloud_allowed=True),
                note("public", "zebra", cloud_allowed=True)]
    assert [m["id"] for m in select_memory(memories, BOT, True, "zebra", [])] == ["public"]


def test_handoff_and_no_match() -> None:
    """Unrelated notes stay out; oversized handoffs still fail explicitly."""
    assert select_memory([note("n", "zebra")], BOT, False, "unicorn", []) == []
    with pytest.raises(ProviderError):
        select_memory([], BOT, False, "task", [{"output": "x" * 25000}])
    chosen = select_memory([note(str(i), "zebra " * 400) for i in range(40)], BOT, False,
                           "zebra", [{"output": "x" * 16000}])
    build_context(BOT, chosen, "zebra", [{"output": "x" * 16000}])


def test_explicit_notes_override_keyword_ranking_without_extra_notes() -> None:
    """Required preferences cannot be displaced by a misleading topical title."""
    memories = [note("my preferences", "Use source-qualified claims", category="preference"),
                note("zebra migration preferences", "Synthetic demo data", category="demo")]
    assert select_memory(memories, BOT, False, "zebra migration", [], ["my preferences"]) == memories[:1]
    assert select_memory(memories, BOT, False, "zebra migration", []) == memories[:1]
    assert select_memory(memories, BOT, False, "zebra migration", [], [memories[1]["id"]]) == memories[1:]


@pytest.mark.parametrize("extra,cloud", [({"active": False}, False), ({"owner_id": "other"}, False), ({}, True)])
def test_required_notes_cannot_bypass_permissions(extra: dict, cloud: bool) -> None:
    """An explicit selection never grants sharing or cloud permission."""
    with pytest.raises(ProviderError, match="not permitted"):
        select_memory([note("required", "content", **extra)], BOT, cloud, "task", [], ["required"])


def test_missing_or_oversized_required_notes_are_not_silently_dropped() -> None:
    """Required-note errors are explicit, including after handoff growth."""
    with pytest.raises(ProviderError, match="missing"):
        select_memory([], BOT, False, "task", [], ["deleted"])
    memories = [note(str(index), "x" * 3000) for index in range(8)]
    with pytest.raises(ProviderError, match="Context is too large"):
        select_memory(memories, BOT, False, "task", [], [m["id"] for m in memories])
