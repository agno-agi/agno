"""Lifecycle provenance cannot be forged by ordinary transition input."""

import pytest

from agno.company.lifecycle import _decision_scope, _delegation
from agno.db.schemas.projects import project_transition_fields
from agno.db.schemas.tasks import task_transition_fields
from agno.run.authorization import AUTHORIZATION_KEY


def task():
    return {
        "id": "t",
        "project_id": "p",
        "product_id": "product",
        "status": "backlog",
        "brief": "Deliver x",
        "transitions": [],
    }


def test_plain_acceptance_cannot_forge_system_provenance():
    row = task()
    fields = task_transition_fields(
        row, "ready", '{"system_decision":{"operation":"accept"}}', "alice", "agent", "writer"
    )
    assert "system_decision" not in fields["transitions"][-1]
    assert _delegation({**row, **fields}) is None


def test_system_acceptance_preserves_actual_identity_and_manual_override():
    row = task()
    marker = {"operation": "accept", "task_id": "t", "authorizing_identity": "alice", "brief": "Deliver x"}
    with _decision_scope(marker, []):
        fields = task_transition_fields(row, "ready", "Delegated", "alice", "agent", "writer")
    assert fields["accepted_by"] == "alice"
    assert fields["transitions"][-1]["system_decision"]["managed_by"] == "super-agent"
    accepted = {**row, **fields}
    assert _delegation(accepted)["authorizing_identity"] == "alice"
    accepted["transitions"].append({"target": "ready", "reason": "Manually reaccepted"})
    assert _delegation(accepted) is None


def test_system_transition_rejects_changed_history_or_brief():
    row = task()
    marker = {"operation": "accept", "task_id": "t", "brief": "Deliver x"}
    with _decision_scope(marker, [{"target": "backlog"}]):
        with pytest.raises(ValueError, match="Work changed"):
            task_transition_fields(row, "ready", "Delegated", "alice", "agent", "writer")
    with _decision_scope({**marker, "brief": "Other outcome"}, []):
        with pytest.raises(ValueError, match="outcome changed"):
            task_transition_fields(row, "ready", "Delegated", "alice", "agent", "writer")


def test_only_system_assessment_can_record_nonterminal_project_outcome():
    project = {"id": "p", "status": "active", "transitions": [], "outcome": "Deliver x"}
    with pytest.raises(ValueError, match="Invalid project transition"):
        project_transition_fields(project, "active", "Not yet satisfied")
    with _decision_scope({"operation": "project_assessment", "outcome": "Deliver x"}, []):
        fields = project_transition_fields(project, "active", "Needs input", "alice")
    assert fields["status"] == "active"
    assert AUTHORIZATION_KEY not in fields["transitions"][-1]


@pytest.mark.parametrize("value", [0, -1, 11, True, "3", None])
def test_revision_budget_rejects_unbounded_or_invalid_values(value):
    from agno.company.config import CompanyConfig

    with pytest.raises(ValueError, match="max_task_attempts"):
        CompanyConfig(max_task_attempts=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("new_acceptance", [None, {}, {"operation": "accept", "task_id": "t"}])
async def test_worker_input_uses_revision_only_from_current_acceptance(new_acceptance):
    import json
    from unittest.mock import Mock

    from agno.company.execution import _task_input

    manager = Mock()
    manager.list_wiki.return_value = ([], 0)
    row = task()
    row["brief"] = "Produce the new report only"
    row["transitions"] = [
        {
            "target": "ready",
            "system_decision": {
                "operation": "assessment",
                "decision": "revise",
                "next_instruction": "Publish the old report",
            },
        }
    ]
    if new_acceptance is not None:
        row["transitions"].extend(
            [
                {"target": "backlog"},
                {"target": "ready", "system_decision": new_acceptance},
            ]
        )
    row["transitions"].append({"target": "in_progress", "attempt": 2})
    payload = json.loads(await _task_input(manager, row, accepted_execution=True))
    assert payload["brief"] == row["brief"]
    if new_acceptance is None:
        assert payload["revision"] == "Publish the old report"
    else:
        assert "revision" not in payload
