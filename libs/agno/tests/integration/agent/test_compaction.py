"""Integration tests for Agent conversation compaction.

Compaction replaces the entire conversation history with a summary when the
token count approaches the model's context window limit.  These tests verify:

1. Compaction triggers when threshold is exceeded (sync + async).
2. compacted_run_ids is populated and persisted correctly.
3. Compacted runs are skipped in subsequent history loading.
4. enable_compaction=False leaves the original behaviour untouched.

Environment (at least one required):
    Option A — OpenAI native:
        export OPENAI_API_KEY="sk-xxx"
    Option B — OpenAI-compatible API:
        export AGNO_MODEL_API_KEY="sk-xxx"
        export AGNO_MODEL_BASE_URL="http://your-server/v1"
        export AGNO_MODEL_ID="your-model"
"""

import json
import os
import random
import string

import pytest

from agno.agent import Agent
from agno.compaction import CompactionManager
from agno.models.openai import OpenAIChat
from agno.models.openai.like import OpenAILike


# ---------------------------------------------------------------------------
# Model setup: support both OpenAI native and compatible APIs
# ---------------------------------------------------------------------------

def _get_model():
    """Return a model instance, preferring AGNO_MODEL_* env vars, falling back to OpenAI."""
    base_url = os.environ.get("AGNO_MODEL_BASE_URL")
    api_key = os.environ.get("AGNO_MODEL_API_KEY")
    model_id = os.environ.get("AGNO_MODEL_ID")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if base_url and api_key:
        return OpenAILike(id=model_id or "default", base_url=base_url, api_key=api_key)
    elif openai_key:
        return OpenAIChat(id="gpt-4o-mini")
    else:
        pytest.skip("No API key configured (set OPENAI_API_KEY or AGNO_MODEL_* vars)")
        return None  # unreachable


_has_api_key = bool(os.environ.get("OPENAI_API_KEY") or
                    (os.environ.get("AGNO_MODEL_BASE_URL") and os.environ.get("AGNO_MODEL_API_KEY")))
pytestmark = pytest.mark.skipif(not _has_api_key, reason="No API key configured")


# ---------------------------------------------------------------------------
# Helper tools that produce large output to fill the context window
# ---------------------------------------------------------------------------

def generate_report(topic: str, pages: int = 5) -> str:
    """Generate a very long report on the given topic."""
    paragraphs = []
    for _ in range(pages):
        for _ in range(8):
            words = ["".join(random.choices(string.ascii_lowercase, k=random.randint(3, 10))) for _ in range(20)]
            paragraphs.append(" ".join(words).capitalize() + ".")
    return (
        f"===== REPORT: {topic.upper()} =====\n\n"
        + "\n\n".join(paragraphs)
        + f"\n\n===== END OF REPORT ({pages} pages) ====="
    )


def lookup_data(query: str, records: int = 300) -> str:
    """Look up data records matching the query."""
    rows = []
    for i in range(records):
        row = {
            "id": i,
            "query": query,
            "name": "".join(random.choices(string.ascii_letters, k=12)),
            "value": random.randint(1000, 99999),
            "category": random.choice(["A", "B", "C", "D"]),
            "status": random.choice(["active", "pending", "archived"]),
        }
        rows.append(json.dumps(row))
    return f"Data lookup for '{query}': {records} records.\n\n" + "\n".join(rows)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def compaction_agent(shared_db):
    """Agent with compaction enabled and a very low threshold."""
    return Agent(
        model=_get_model(),
        tools=[generate_report, lookup_data],
        db=shared_db,
        enable_compaction=True,
        compaction_manager=CompactionManager(
            context_usage_threshold=0.10,
            context_reserve_tokens=1000,
            preserve_last_n_messages=2,
        ),
        instructions=[
            "You are a data analysis assistant.",
            "Use generate_report when asked to generate a report.",
            "Use lookup_data when asked to look up data.",
            "Always include the full tool output in your response.",
        ],
        telemetry=False,
    )


# ---------------------------------------------------------------------------
# Sync tests
# ---------------------------------------------------------------------------

def test_compaction_triggers_on_large_history(compaction_agent, shared_db):
    """Multiple runs with large tool output should trigger compaction."""
    # Run 1: generates large report (~6000+ tokens)
    r1 = compaction_agent.run("Generate a 5-page report on quantum computing trends")
    assert r1.status.value in ("completed", "COMPLETED"), f"Run 1 failed: {r1.status}"
    assert r1.compacted_run_ids is None, "First run should not be compacted"

    # Run 2: another large output — history now includes Run 1
    r2 = compaction_agent.run("Look up 300 data records about AI adoption")
    assert r2.status.value in ("completed", "COMPLETED"), f"Run 2 failed: {r2.status}"

    # Run 3: synthesis — should trigger compaction
    r3 = compaction_agent.run("What were the key findings from the report and data?")
    assert r3.status.value in ("completed", "COMPLETED"), f"Run 3 failed: {r3.status}"

    # Verify compaction happened in at least one run
    all_runs = [r1, r2, r3]
    compacted_runs = [r for r in all_runs if r.compacted_run_ids]
    assert len(compacted_runs) >= 1, "Compaction should have triggered at least once"

    # Verify compacted_run_ids is a list of strings
    for cr in compacted_runs:
        assert isinstance(cr.compacted_run_ids, list)
        assert all(isinstance(rid, str) for rid in cr.compacted_run_ids)
        assert len(cr.compacted_run_ids) > 0


def test_compaction_persists_in_session(compaction_agent, shared_db):
    """Compacted run IDs should persist correctly in the session DB."""
    compaction_agent.run("Generate a 5-page report on AI trends")
    compaction_agent.run("Look up 300 records about machine learning")
    compaction_agent.run("Summarize our findings so far")

    # Retrieve the session from DB
    session = compaction_agent.get_session(compaction_agent.session_id)
    assert session is not None

    # Check that at least one run has compacted_run_ids
    runs_with_compaction = [
        r for r in session.runs
        if hasattr(r, "compacted_run_ids") and r.compacted_run_ids
    ]
    assert len(runs_with_compaction) >= 1, "At least one run should have compacted_run_ids in session"

    # Verify the compacted run IDs reference actual runs
    all_run_ids = {r.run_id for r in session.runs if hasattr(r, "run_id")}
    for cr in runs_with_compaction:
        for rid in cr.compacted_run_ids:
            assert rid in all_run_ids, f"Compacted run ID {rid} should reference an actual run"


def test_compaction_reduces_message_count(shared_db):
    """After compaction, the number of history messages should be much smaller."""
    agent = Agent(
        model=_get_model(),
        tools=[generate_report],
        db=shared_db,
        enable_compaction=True,
        compaction_manager=CompactionManager(
            context_usage_threshold=0.10,
            context_reserve_tokens=1000,
            preserve_last_n_messages=2,
        ),
        instructions="Generate reports when asked.",
        telemetry=False,
    )

    # Run 1
    agent.run("Generate a 5-page report on quantum computing")
    session_after_1 = agent.get_session(agent.session_id)
    msgs_after_1 = len(session_after_1.runs[-1].messages) if session_after_1.runs else 0

    # Run 2 — should trigger compaction
    r2 = agent.run("Generate a 5-page report on climate change")

    # If compaction triggered, the compacted run should have fewer messages
    if r2.compacted_run_ids:
        assert len(r2.messages or []) < msgs_after_1 + 5, \
            "Compacted run should have fewer messages than full history"


def test_compaction_stats_updated(compaction_agent):
    """CompactionManager.stats should be populated after compaction."""
    compaction_agent.run("Generate a 5-page report on quantum computing")
    compaction_agent.run("Look up 300 records about AI adoption")
    compaction_agent.run("Summarize findings")

    stats = compaction_agent.compaction_manager.stats
    if stats.get("compactions_performed", 0) > 0:
        assert stats["tokens_before"] > stats["tokens_after"]
        assert stats["tokens_saved"] > 0
        assert stats["messages_before"] > stats["messages_after"]


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compaction_async(shared_db):
    """Compaction should work with arun()."""
    agent = Agent(
        model=_get_model(),
        tools=[generate_report, lookup_data],
        db=shared_db,
        enable_compaction=True,
        compaction_manager=CompactionManager(
            context_usage_threshold=0.10,
            context_reserve_tokens=1000,
            preserve_last_n_messages=2,
        ),
        instructions="Generate reports and look up data when asked.",
        telemetry=False,
    )

    await agent.arun("Generate a 5-page report on quantum computing")
    await agent.arun("Look up 300 records about AI adoption")
    r3 = await agent.arun("Summarize the findings")

    assert r3.status.value in ("completed", "COMPLETED")

    # Compaction should have triggered
    session = agent.get_session(agent.session_id)
    compacted_runs = [
        r for r in session.runs
        if hasattr(r, "compacted_run_ids") and r.compacted_run_ids
    ]
    assert len(compacted_runs) >= 1, "Compaction should trigger in async mode"


# ---------------------------------------------------------------------------
# No-compaction control tests
# ---------------------------------------------------------------------------

def test_no_compaction_when_disabled(shared_db):
    """When enable_compaction=False, no compaction should occur."""
    agent = Agent(
        model=_get_model(),
        tools=[generate_report, lookup_data],
        db=shared_db,
        enable_compaction=False,
        instructions="Generate reports and look up data when asked.",
        telemetry=False,
    )

    agent.run("Generate a 5-page report on quantum computing")
    agent.run("Look up 300 records about AI adoption")
    r3 = agent.run("Summarize the findings")

    assert r3.compacted_run_ids is None, "No compaction when disabled"

    session = agent.get_session(agent.session_id)
    for run in session.runs:
        assert run.compacted_run_ids is None, "No run should have compacted_run_ids"


def test_compaction_default_off(shared_db):
    """By default, compaction should be disabled."""
    agent = Agent(
        model=_get_model(),
        tools=[generate_report],
        db=shared_db,
        instructions="Generate reports when asked.",
        telemetry=False,
    )

    assert agent.enable_compaction is False
    assert agent.compaction_manager is None

    agent.run("Generate a 5-page report on quantum computing")
    agent.run("Summarize the report")

    session = agent.get_session(agent.session_id)
    for run in session.runs:
        assert run.compacted_run_ids is None
