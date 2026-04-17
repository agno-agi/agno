"""Integration tests for Team conversation compaction.

Compaction replaces the Team leader's conversation history with a summary when
the token count approaches the model's context window limit.  These tests verify:

1. Compaction triggers when the Team leader's history exceeds the threshold.
2. compacted_run_ids is populated on TeamRunOutput and persisted in session.
3. Member agent runs are NOT compacted (they manage their own sessions).
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
from agno.team import Team


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
# Helper tools
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
        }
        rows.append(json.dumps(row))
    return f"Data lookup for '{query}': {records} records.\n\n" + "\n".join(rows)


def analyze_metrics(dataset: str, dimensions: int = 200) -> str:
    """Analyze metrics for a dataset."""
    lines = [f"Metrics for '{dataset}' ({dimensions} dimensions):\n"]
    for d in range(dimensions):
        values = [round(random.uniform(0, 100), 2) for _ in range(10)]
        lines.append(json.dumps({"dim": d, "mean": round(sum(values) / len(values), 2), "values": values}))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def researcher():
    return Agent(
        name="Researcher",
        model=_get_model(),
        tools=[generate_report],
        instructions="Generate detailed reports when asked. Return the full report.",
        telemetry=False,
    )


@pytest.fixture
def data_analyst():
    return Agent(
        name="DataAnalyst",
        model=_get_model(),
        tools=[lookup_data],
        instructions="Look up data when asked. Return a summary of the data.",
        telemetry=False,
    )


@pytest.fixture
def metrics_analyst():
    return Agent(
        name="MetricsAnalyst",
        model=_get_model(),
        tools=[analyze_metrics],
        instructions="Analyze metrics when asked. Return a summary.",
        telemetry=False,
    )


@pytest.fixture
def compaction_team(researcher, data_analyst, metrics_analyst, shared_db):
    """Team with compaction enabled and a very low threshold."""
    return Team(
        name="AnalysisTeam",
        model=_get_model(),
        members=[researcher, data_analyst, metrics_analyst],
        mode="coordinate",
        db=shared_db,
        enable_compaction=True,
        compaction_manager=CompactionManager(
            context_usage_threshold=0.10,
            context_reserve_tokens=1000,
            preserve_last_n_messages=2,
        ),
        instructions=[
            "You are the team leader. Delegate tasks to specialist agents.",
            "After receiving results, provide a brief synthesis.",
        ],
        telemetry=False,
    )


# ---------------------------------------------------------------------------
# Sync tests
# ---------------------------------------------------------------------------

def test_team_compaction_triggers(compaction_team, shared_db):
    """Multiple delegation rounds should trigger compaction on the Team leader."""
    # Round 1: delegate to researcher
    r1 = compaction_team.run("Have the Researcher generate a 5-page report on quantum computing")
    assert r1.status.value in ("completed", "COMPLETED"), f"Run 1 failed: {r1.status}"
    assert r1.compacted_run_ids is None, "First run should not be compacted"

    # Round 2: delegate to data analyst
    r2 = compaction_team.run("Have the DataAnalyst look up 300 records about AI adoption")
    assert r2.status.value in ("completed", "COMPLETED"), f"Run 2 failed: {r2.status}"

    # Round 3: delegate to metrics analyst
    r3 = compaction_team.run("Have the MetricsAnalyst analyze metrics for 'climate_impact'")
    assert r3.status.value in ("completed", "COMPLETED"), f"Run 3 failed: {r3.status}"

    # Round 4: synthesis
    r4 = compaction_team.run("Summarize all findings from the three analyses")
    assert r4.status.value in ("completed", "COMPLETED"), f"Run 4 failed: {r4.status}"

    # At least one run should have triggered compaction
    all_runs = [r1, r2, r3, r4]
    compacted_runs = [r for r in all_runs if r.compacted_run_ids]
    assert len(compacted_runs) >= 1, "Compaction should trigger in at least one team run"

    # Verify compacted_run_ids format
    for cr in compacted_runs:
        assert isinstance(cr.compacted_run_ids, list)
        assert all(isinstance(rid, str) for rid in cr.compacted_run_ids)


def test_team_compaction_persists_in_session(compaction_team, shared_db):
    """Compacted run IDs should persist in the team session DB."""
    compaction_team.run("Have the Researcher generate a 5-page report on AI trends")
    compaction_team.run("Have the DataAnalyst look up 300 records about ML adoption")
    compaction_team.run("Summarize all findings")

    session = compaction_team.get_session(compaction_team.session_id)
    assert session is not None

    # At least one team-level run should have compacted_run_ids
    team_runs = [r for r in session.runs if not getattr(r, "parent_run_id", None)]
    compacted_team_runs = [
        r for r in team_runs
        if hasattr(r, "compacted_run_ids") and r.compacted_run_ids
    ]
    assert len(compacted_team_runs) >= 1, "At least one team run should have compacted_run_ids"


def test_team_compaction_not_on_member_runs(compaction_team, shared_db):
    """Member agent runs should NOT have compacted_run_ids."""
    compaction_team.run("Have the Researcher generate a 5-page report on quantum computing")
    compaction_team.run("Have the DataAnalyst look up 300 records about AI adoption")
    compaction_team.run("Summarize findings")

    session = compaction_team.get_session(compaction_team.session_id)
    assert session is not None

    # Member runs have parent_run_id set
    member_runs = [r for r in session.runs if getattr(r, "parent_run_id", None)]
    for mr in member_runs:
        assert getattr(mr, "compacted_run_ids", None) is None, \
            "Member agent runs should not have compacted_run_ids"


def test_team_compaction_stats(compaction_team):
    """CompactionManager.stats should be populated after compaction."""
    compaction_team.run("Have the Researcher generate a 5-page report on quantum computing")
    compaction_team.run("Have the DataAnalyst look up 300 records about AI adoption")
    compaction_team.run("Summarize findings")

    stats = compaction_team.compaction_manager.stats
    if stats.get("compactions_performed", 0) > 0:
        assert stats["tokens_before"] > stats["tokens_after"]
        assert stats["tokens_saved"] > 0
        assert stats["messages_before"] > stats["messages_after"]


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_team_compaction_async(shared_db):
    """Compaction should work with team.arun()."""
    researcher = Agent(
        name="Researcher",
        model=_get_model(),
        tools=[generate_report],
        instructions="Generate reports when asked.",
        telemetry=False,
    )
    data_analyst = Agent(
        name="DataAnalyst",
        model=_get_model(),
        tools=[lookup_data],
        instructions="Look up data when asked.",
        telemetry=False,
    )

    team = Team(
        name="AsyncTeam",
        model=_get_model(),
        members=[researcher, data_analyst],
        mode="coordinate",
        db=shared_db,
        enable_compaction=True,
        compaction_manager=CompactionManager(
            context_usage_threshold=0.10,
            context_reserve_tokens=1000,
            preserve_last_n_messages=2,
        ),
        instructions="Delegate tasks to specialist agents.",
        telemetry=False,
    )

    await team.arun("Have the Researcher generate a 5-page report on AI")
    await team.arun("Have the DataAnalyst look up 300 records about ML")
    r3 = await team.arun("Summarize findings")

    assert r3.status.value in ("completed", "COMPLETED")

    session = team.get_session(team.session_id)
    compacted_runs = [
        r for r in session.runs
        if hasattr(r, "compacted_run_ids") and r.compacted_run_ids
    ]
    assert len(compacted_runs) >= 1, "Compaction should trigger in async team mode"


# ---------------------------------------------------------------------------
# No-compaction control tests
# ---------------------------------------------------------------------------

def test_team_no_compaction_when_disabled(shared_db):
    """When enable_compaction=False, no compaction should occur on team."""
    researcher = Agent(
        name="Researcher",
        model=_get_model(),
        tools=[generate_report],
        instructions="Generate reports when asked.",
        telemetry=False,
    )

    team = Team(
        name="NoCompactionTeam",
        model=_get_model(),
        members=[researcher],
        mode="coordinate",
        db=shared_db,
        enable_compaction=False,
        instructions="Delegate tasks to the Researcher.",
        telemetry=False,
    )

    team.run("Have the Researcher generate a 5-page report on quantum computing")
    team.run("Have the Researcher generate a 5-page report on AI trends")
    r3 = team.run("Summarize all reports")

    assert r3.compacted_run_ids is None, "No compaction when disabled"

    session = team.get_session(team.session_id)
    for run in session.runs:
        assert run.compacted_run_ids is None


def test_team_compaction_default_off(shared_db):
    """By default, compaction should be disabled on teams."""
    researcher = Agent(
        name="Researcher",
        model=_get_model(),
        tools=[generate_report],
        instructions="Generate reports when asked.",
        telemetry=False,
    )

    team = Team(
        name="DefaultTeam",
        model=_get_model(),
        members=[researcher],
        mode="coordinate",
        db=shared_db,
        instructions="Delegate tasks.",
        telemetry=False,
    )

    assert team.enable_compaction is False
    assert team.compaction_manager is None
