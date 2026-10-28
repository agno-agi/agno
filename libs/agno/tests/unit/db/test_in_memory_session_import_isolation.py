"""Imported runs must be detached from the caller's mutable data."""

import pytest

from agno.db.in_memory import InMemoryDb
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession


@pytest.mark.parametrize(
    "session_class,run_class,component_key",
    [
        (AgentSession, RunOutput, "agent_id"),
        (TeamSession, TeamRunOutput, "team_id"),
        (WorkflowSession, WorkflowRunOutput, "workflow_id"),
    ],
    ids=["agent", "team", "workflow"],
)
@pytest.mark.parametrize("as_dict", [False, True], ids=["run_object", "run_dict"])
@pytest.mark.parametrize("bulk", [False, True], ids=["single", "bulk"])
def test_imported_run_metadata_is_isolated(session_class, run_class, component_key, as_dict, bulk):
    db = InMemoryDb()
    metadata = {"nested": {"labels": ["before"]}}
    component = {component_key: "component"}
    run = run_class(run_id="r1", session_id="s1", metadata=metadata, **component)
    incoming_run = run.to_dict() if as_dict else run
    session = session_class(session_id="s1", runs=[incoming_run], **component)

    if bulk:
        db.upsert_sessions([session])
    else:
        db.upsert_session(session)

    # Warm the agent history cache before mutating the source, so cached and
    # uncached reads must continue to agree after the mutation.
    assert db.get_session("s1").runs[0].metadata == {"nested": {"labels": ["before"]}}
    metadata["nested"]["labels"].append("after")

    expected = {"nested": {"labels": ["before"]}}
    assert db.get_run("r1", deserialize=False)["metadata"] == expected
    assert db.get_session("s1").runs[0].metadata == expected
    assert db.get_session("s1", runs_limit=1).runs[0].metadata == expected
    assert db.get_runs(session_id="s1")[0].metadata == expected
