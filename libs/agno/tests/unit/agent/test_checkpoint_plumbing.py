"""Unit tests for the checkpoint plumbing (PR 1 of run-checkpointing).

Scope: additive plumbing only — no behavior change. Covers:
- RunStatus.interrupted enum value
- New optional fields on RunOutput and their dict round-trip
- Agent constructor accepts checkpoint and resolves the None default
- AgentOS-level checkpoint inheritance respects the agent override
"""

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.run import RunStatus
from agno.run.agent import RunOutput

# ---------------------------------------------------------------------------
# RunStatus enum
# ---------------------------------------------------------------------------


def test_run_status_interrupted_exists():
    assert RunStatus.interrupted.value == "INTERRUPTED"
    assert RunStatus("INTERRUPTED") is RunStatus.interrupted


# ---------------------------------------------------------------------------
# RunOutput new fields
# ---------------------------------------------------------------------------


def test_run_output_new_fields_default_to_none():
    run = RunOutput(run_id="r1")
    assert run.last_checkpoint_at_message_index is None
    assert run.forked_from_run_id is None
    assert run.forked_from_message_index is None


def test_run_output_round_trip_with_checkpoint_fields():
    run = RunOutput(
        run_id="r1",
        session_id="s1",
        last_checkpoint_at_message_index=14,
        forked_from_run_id="r0",
        forked_from_message_index=10,
    )

    d = run.to_dict()
    assert d["last_checkpoint_at_message_index"] == 14
    assert d["forked_from_run_id"] == "r0"
    assert d["forked_from_message_index"] == 10

    restored = RunOutput.from_dict(d)
    assert restored.last_checkpoint_at_message_index == 14
    assert restored.forked_from_run_id == "r0"
    assert restored.forked_from_message_index == 10
    # parent_run_id is independent of fork lineage (ADR-007)
    assert restored.parent_run_id is None


def test_run_output_dict_excludes_none_checkpoint_fields():
    run = RunOutput(run_id="r1")
    d = run.to_dict()
    # Optional checkpoint/fork fields should not appear when None
    assert "last_checkpoint_at_message_index" not in d
    assert "forked_from_run_id" not in d
    assert "forked_from_message_index" not in d


# ---------------------------------------------------------------------------
# Agent.checkpoint param + None resolution
# ---------------------------------------------------------------------------


def test_agent_default_checkpoint_is_none_pre_init():
    """Constructor leaves checkpoint as None so OS-level inheritance can fill it."""
    agent = Agent(name="a")
    assert agent.checkpoint is None


def test_agent_initialize_resolves_none_to_runs():
    agent = Agent(name="a")
    agent.initialize_agent()
    assert agent.checkpoint == "runs"


@pytest.mark.parametrize("level", ["runs", "steps"])
def test_agent_initialize_preserves_explicit_level(level):
    agent = Agent(name="a", checkpoint=level)
    agent.initialize_agent()
    assert agent.checkpoint == level


def test_agent_initialize_raises_on_tools_level():
    agent = Agent(name="a", checkpoint="tools")
    with pytest.raises(NotImplementedError):
        agent.initialize_agent()


def test_agent_initialize_raises_on_invalid_level():
    agent = Agent(name="a", checkpoint="bogus")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        agent.initialize_agent()


# ---------------------------------------------------------------------------
# AgentOS-level inheritance
# ---------------------------------------------------------------------------


def test_agentos_checkpoint_propagates_when_agent_has_none():
    agent = Agent(name="a", id="a-id")
    assert agent.checkpoint is None

    AgentOS(agents=[agent], db=InMemoryDb(), checkpoint="steps", telemetry=False)

    # Inherited from OS, then resolved by initialize_agent
    assert agent.checkpoint == "steps"


def test_agentos_checkpoint_does_not_override_agent_setting():
    agent = Agent(name="a", id="a-id", checkpoint="runs")

    AgentOS(agents=[agent], db=InMemoryDb(), checkpoint="steps", telemetry=False)

    # Agent-level wins
    assert agent.checkpoint == "runs"


def test_agentos_default_checkpoint_is_none():
    os_app = AgentOS(db=InMemoryDb(), telemetry=False)
    assert os_app.checkpoint is None


def test_agentos_without_checkpoint_leaves_agent_at_runs_default():
    agent = Agent(name="a", id="a-id")

    AgentOS(agents=[agent], db=InMemoryDb(), telemetry=False)

    # No OS-level setting → agent resolves to "runs" via initialize_agent
    assert agent.checkpoint == "runs"
