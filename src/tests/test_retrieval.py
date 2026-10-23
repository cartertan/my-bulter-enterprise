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
