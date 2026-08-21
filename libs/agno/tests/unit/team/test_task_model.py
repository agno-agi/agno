"""Unit tests for Task, TaskList, and session_state helpers."""

import pytest

from agno.team.task import (
    TASK_LIST_KEY,
    Task,
    TaskList,
    TaskStatus,
    load_task_list,
    save_task_list,
)


class TestTaskStatus:
    def test_enum_values(self):
        assert TaskStatus.pending == "pending"
        assert TaskStatus.in_progress == "in_progress"
        assert TaskStatus.completed == "completed"
        assert TaskStatus.failed == "failed"
        assert TaskStatus.cancelled == "cancelled"
        assert TaskStatus.blocked == "blocked"

    def test_from_string(self):
        assert TaskStatus("pending") == TaskStatus.pending
        assert TaskStatus("completed") == TaskStatus.completed


class TestTask:
    def test_auto_id(self):
        task = Task(title="Test")
        assert task.id  # non-empty
        assert len(task.id) == 8

    def test_auto_created_at(self):
        task = Task(title="Test")
        assert task.created_at > 0

    def test_explicit_id(self):
        task = Task(id="abc", title="Test")
        assert task.id == "abc"

    def test_default_status(self):
        task = Task(title="Test")
        assert task.status == TaskStatus.pending

    def test_to_dict(self):
        task = Task(id="t1", title="Do thing", description="Details", assignee="agent-a")
        d = task.to_dict()
        assert d["id"] == "t1"
        assert d["title"] == "Do thing"
        assert d["description"] == "Details"
        assert d["status"] == "pending"
        assert d["assignee"] == "agent-a"

    def test_from_dict(self):
        data = {
            "id": "t1",
            "title": "Do thing",
            "description": "Details",
            "status": "in_progress",
            "assignee": "agent-a",
            "dependencies": ["t0"],
            "result": "Done",
            "notes": ["note1"],
            "created_at": 1000.0,
        }
        task = Task.from_dict(data)
        assert task.id == "t1"
        assert task.status == TaskStatus.in_progress
        assert task.dependencies == ["t0"]
        assert task.result == "Done"
        assert task.notes == ["note1"]

    def test_roundtrip(self):
        task = Task(id="t1", title="Test", description="desc", assignee="a")
        d = task.to_dict()
        task2 = Task.from_dict(d)
        assert task2.id == task.id
        assert task2.title == task.title
        assert task2.description == task.description
        assert task2.assignee == task.assignee
        assert task2.status == task.status


class TestTaskList:
    def test_create_task(self):
        tl = TaskList()
        task = tl.create_task("Do thing", description="Details")
        assert len(tl.tasks) == 1
        assert task.title == "Do thing"
        assert task.status == TaskStatus.pending

    def test_create_task_invalidates_prior_goal_completion(self):
        tl = TaskList(goal_complete=True, completion_summary="Previous goal complete")

        tl.create_task("Follow-up task")

        assert tl.goal_complete is False
        assert tl.completion_summary is None

    def test_get_task(self):
        tl = TaskList()
        t = tl.create_task("Task A")
        found = tl.get_task(t.id)
        assert found is t

    def test_get_task_not_found(self):
        tl = TaskList()
        assert tl.get_task("nonexistent") is None

    def test_update_task(self):
        tl = TaskList()
        t = tl.create_task("Task A")
        updated = tl.update_task(t.id, status="completed", result="All done")
        assert updated is not None
        assert updated.status == TaskStatus.completed
        assert updated.result == "All done"

    def test_update_task_not_found(self):
        tl = TaskList()
        assert tl.update_task("nonexistent", status="completed") is None

    def test_get_available_tasks(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1")
        t2 = tl.create_task("Task 2")
        t3 = tl.create_task("Task 3", dependencies=[t1.id])
        available = tl.get_available_tasks()
        ids = [t.id for t in available]
        assert t1.id in ids
        assert t2.id in ids
        assert t3.id not in ids  # blocked by t1

    def test_get_available_tasks_with_assignee(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1", assignee="agent-a")
        t2 = tl.create_task("Task 2", assignee="agent-b")
        available = tl.get_available_tasks(for_assignee="agent-a")
        ids = [t.id for t in available]
        assert t1.id in ids
        assert t2.id not in ids

    def test_all_terminal_empty(self):
        tl = TaskList()
        assert tl.all_terminal() is False

    def test_all_terminal_all_completed(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1")
        t2 = tl.create_task("Task 2")
        tl.update_task(t1.id, status="completed")
        tl.update_task(t2.id, status="completed")
        assert tl.all_terminal() is True

    def test_all_terminal_mixed(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1")
        t2 = tl.create_task("Task 2")
        tl.update_task(t1.id, status="completed")
        tl.update_task(t2.id, status="failed")
        assert tl.all_terminal() is True

    def test_all_terminal_with_cancelled(self):
        tl = TaskList()
        task = tl.create_task("Task 1")
        tl.update_task(task.id, status="cancelled")

        assert tl.all_terminal() is True

    def test_all_terminal_not_done(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1")
        tl.create_task("Task 2")
        tl.update_task(t1.id, status="completed")
        assert tl.all_terminal() is False


class TestTaskListDependencies:
    def test_dependency_blocks_task(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1")
        t2 = tl.create_task("Task 2", dependencies=[t1.id])
        assert t2.status == TaskStatus.blocked

    def test_completing_dependency_unblocks(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1")
        t2 = tl.create_task("Task 2", dependencies=[t1.id])
        assert t2.status == TaskStatus.blocked
        tl.update_task(t1.id, status="completed")
        assert t2.status == TaskStatus.pending

    def test_multiple_dependencies(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1")
        t2 = tl.create_task("Task 2")
        t3 = tl.create_task("Task 3", dependencies=[t1.id, t2.id])
        assert t3.status == TaskStatus.blocked
        tl.update_task(t1.id, status="completed")
        assert t3.status == TaskStatus.blocked  # t2 still pending
        tl.update_task(t2.id, status="completed")
        assert t3.status == TaskStatus.pending

    def test_cancelled_dependency_cancels_descendants(self):
        tl = TaskList()
        parent = tl.create_task("Parent")
        child = tl.create_task("Child", dependencies=[parent.id])
        grandchild = tl.create_task("Grandchild", dependencies=[child.id])

        tl.update_task(parent.id, status="cancelled", result="No longer needed")

        assert child.status == TaskStatus.cancelled
        assert grandchild.status == TaskStatus.cancelled
        assert "dependency was cancelled" in child.result
        assert "dependency was cancelled" in grandchild.result

    def test_failed_dependent_can_reopen_after_dependency_recovers_and_terminal_results_are_cleared(self):
        tl = TaskList()
        parent = tl.create_task("Parent")
        child = tl.create_task("Child", dependencies=[parent.id])

        tl.update_task(parent.id, status="failed", result="Temporary upstream failure")

        assert child.status == TaskStatus.failed
        assert child.result == "Automatically failed: a dependency failed."

        tl.update_task(parent.id, status="pending")

        assert parent.status == TaskStatus.pending
        assert parent.result is None

        tl.update_task(parent.id, status="completed", result="Recovered upstream result")

        # Recovery does not silently retry terminal descendants. The leader must
        # explicitly reopen the failed child once its dependencies are healthy.
        assert child.status == TaskStatus.failed
        tl.update_task(child.id, status="pending")

        assert child.status == TaskStatus.pending
        assert child.result is None

    def test_cancelled_task_cannot_be_reopened_through_task_list(self):
        task_list = TaskList()
        task = task_list.create_task("Cancelled work")
        task_list.update_task(task.id, status=TaskStatus.cancelled, result="Cancelled intentionally")
        before = task.to_dict()

        with pytest.raises(ValueError, match="Cancelled tasks cannot be reopened"):
            task_list.update_task(task.id, status=TaskStatus.pending)

        assert task.to_dict() == before

    def test_reopening_work_invalidates_a_prior_goal_completion_marker(self):
        task_list = TaskList()
        task = task_list.create_task("Completed work")
        task_list.update_task(task.id, status=TaskStatus.completed, result="Done")
        task_list.goal_complete = True
        task_list.completion_summary = "Old goal"

        task_list.update_task(task.id, status=TaskStatus.pending)

        assert task_list.goal_complete is False
        assert task_list.completion_summary is None

    def test_terminal_status_change_without_replacement_result_clears_stale_result(self):
        task_list = TaskList()
        task = task_list.create_task("Recovered work")
        task_list.update_task(task.id, status=TaskStatus.failed, result="Member execution error: temporary")

        task_list.update_task(task.id, status=TaskStatus.completed)

        assert task.status == TaskStatus.completed
        assert task.result is None

    @pytest.mark.parametrize("new_status", [TaskStatus.pending, TaskStatus.in_progress, TaskStatus.completed])
    @pytest.mark.parametrize("dependency_id", ["incomplete", "missing"])
    def test_update_task_validates_prospective_dependencies_before_status_change(
        self, new_status: TaskStatus, dependency_id: str
    ):
        task_list = TaskList()
        incomplete = Task(id="incomplete", title="Incomplete dependency")
        task = Task(id="target", title="Target")
        task_list.tasks.extend([incomplete, task])
        before = task.to_dict()

        with pytest.raises(ValueError, match="unresolved dependencies"):
            task_list.update_task(task.id, status=new_status, dependencies=[dependency_id])

        assert task.to_dict() == before

    def test_updating_pending_task_dependencies_can_reconcile_it_to_blocked(self):
        task_list = TaskList()
        dependency = task_list.create_task("Incomplete dependency")
        task = task_list.create_task("Target")

        task_list.update_task(task.id, dependencies=[dependency.id])

        assert task.dependencies == [dependency.id]
        assert task.status == TaskStatus.blocked


class TestTaskListSummary:
    def test_empty_summary(self):
        tl = TaskList()
        assert tl.get_summary_string() == "No tasks created yet."

    def test_summary_with_tasks(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1", assignee="agent-a")
        tl.create_task("Task 2")
        tl.update_task(t1.id, status="completed", result="Done!")
        summary = tl.get_summary_string()
        assert "Task 1" in summary
        assert "Task 2" in summary
        assert "COMPLETED" in summary
        assert "PENDING" in summary
        assert "agent-a" in summary
        assert "Done!" in summary

    def test_summary_truncates_long_results(self):
        tl = TaskList()
        t = tl.create_task("Task 1")
        tl.update_task(t.id, status="completed", result="x" * 300)
        summary = tl.get_summary_string()
        assert "..." in summary

    def test_zero_result_limit_omits_result_previews(self):
        tl = TaskList()
        task = tl.create_task("Task 1")
        tl.update_task(task.id, status="completed", result="PRIVATE_RESULT")

        summary = tl.get_summary_string(result_limit=0)

        assert "Task 1" in summary
        assert "COMPLETED" in summary
        assert "Result:" not in summary
        assert "PRIVATE_RESULT" not in summary
        assert "..." not in summary


class TestTaskListSerialization:
    def test_roundtrip(self):
        tl = TaskList()
        t1 = tl.create_task("Task 1", assignee="agent-a")
        tl.create_task("Task 2", dependencies=[t1.id])
        tl.update_task(t1.id, status="completed", result="Done")
        tl.goal_complete = True
        tl.completion_summary = "All done"

        d = tl.to_dict()
        tl2 = TaskList.from_dict(d)
        assert len(tl2.tasks) == 2
        assert tl2.tasks[0].status == TaskStatus.completed
        assert tl2.tasks[0].result == "Done"
        assert tl2.tasks[1].status == TaskStatus.pending  # unblocked after t1 completed
        assert tl2.goal_complete is True
        assert tl2.completion_summary == "All done"

    def test_from_dict_reconciles_dependency_status_without_overwriting_a_saved_result(self):
        restored = TaskList.from_dict(
            {
                "tasks": [
                    {
                        "id": "upstream",
                        "title": "Fetch data",
                        "status": "failed",
                        "result": "HTTP 503",
                    },
                    {
                        "id": "dependent",
                        "title": "Draft report",
                        "status": "pending",
                        "dependencies": ["upstream"],
                        "result": "PARTIAL DRAFT worth keeping",
                    },
                ]
            }
        )

        dependent = restored.get_task("dependent")
        assert dependent is not None
        assert dependent.status == TaskStatus.failed
        assert dependent.result == "PARTIAL DRAFT worth keeping"


class TestSessionStateHelpers:
    def test_load_empty(self):
        tl = load_task_list(None)
        assert len(tl.tasks) == 0

    def test_load_no_key(self):
        tl = load_task_list({"other": "data"})
        assert len(tl.tasks) == 0

    def test_save_and_load(self):
        state: dict = {}
        tl = TaskList()
        tl.create_task("Task 1")
        save_task_list(state, tl)
        assert TASK_LIST_KEY in state

        tl2 = load_task_list(state)
        assert len(tl2.tasks) == 1
        assert tl2.tasks[0].title == "Task 1"

    def test_save_to_none_state(self):
        tl = TaskList()
        # Should not raise
        save_task_list(None, tl)
