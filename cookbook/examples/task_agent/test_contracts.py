"""Verify record ownership independently of model decisions."""

import task_agent
from agno.run import RunContext


def test_task_ownership_and_idempotence():
    alice = RunContext(
        run_id="alice-run",
        user_id="alice",
        session_id="alice-session",
        session_state={},
    )
    bob = RunContext(
        run_id="bob-run", user_id="bob", session_id="bob-session", session_state={}
    )
    task_agent.tasks["task-1"]["done"] = False
    task_agent.tasks["task-2"]["done"] = False
    assert [task["id"] for task in task_agent.list_tasks(alice)] == ["task-1"]
    assert task_agent.complete_task(alice, "task-2") == "Task not found."
    assert not task_agent.tasks["task-2"]["done"]
    assert task_agent.complete_task(alice, "task-1") == task_agent.complete_task(
        alice, "task-1"
    )
    assert task_agent.list_tasks(alice)[0]["done"]
    assert not task_agent.list_tasks(bob)[0]["done"]
