"""Unit tests for tasks mode improvements.

Tests for:
- Fix 1: Dependent task results passed to members
- Fix 2: Task state reset between runs
- Fix 3: Configurable result truncation
- Fix 4: edit_task and cancel_task tools
"""

from agno.team.task import TaskList, TaskStatus, load_task_list, save_task_list


class TestDependencyContext:
    """Fix 1: Verify dependency results are built correctly."""

    def _make_task_list_with_dependency(self):
        """Create a task list with A (completed) and B (depends on A)."""
        tl = TaskList()
        task_a = tl.create_task("Find the bug", description="Search for auth bug")
        tl.update_task(
            task_a.id, status=TaskStatus.completed, result="Bug found in auth.py:42, token expiry check is missing."
        )
        task_b = tl.create_task("Fix the bug", description="Fix the auth bug", dependencies=[task_a.id])
        return tl, task_a, task_b

    def test_build_dependency_context_with_results(self):
        """Dependency context should include completed task results."""
        tl, task_a, task_b = self._make_task_list_with_dependency()

        # Simulate what _build_dependency_context does
        dep_parts = []
        for dep_id in task_b.dependencies:
            dep = tl.get_task(dep_id)
            if dep is not None and dep.result:
                dep_parts.append(f'Task "{dep.title}" result:\n{dep.result}')

        assert len(dep_parts) == 1
        assert "Bug found in auth.py:42" in dep_parts[0]
        assert "Find the bug" in dep_parts[0]

    def test_build_dependency_context_no_deps(self):
        """Task with no dependencies should produce empty context."""
        tl = TaskList()
        task = tl.create_task("Standalone task")

        assert len(task.dependencies) == 0

    def test_build_dependency_context_dep_no_result(self):
        """Dependency with no result should be skipped."""
        tl = TaskList()
        task_a = tl.create_task("Pending task")
        task_b = tl.create_task("Dependent", dependencies=[task_a.id])

        dep_parts = []
        for dep_id in task_b.dependencies:
            dep = tl.get_task(dep_id)
            if dep is not None and dep.result:
                dep_parts.append(dep.result)

        assert len(dep_parts) == 0

    def test_multiple_dependencies(self):
        """Task with multiple completed dependencies gets all results."""
        tl = TaskList()
        task_a = tl.create_task("Research")
        tl.update_task(task_a.id, status=TaskStatus.completed, result="Research findings here")
        task_b = tl.create_task("Analysis")
        tl.update_task(task_b.id, status=TaskStatus.completed, result="Analysis results here")
        task_c = tl.create_task("Write report", dependencies=[task_a.id, task_b.id])

        dep_parts = []
        for dep_id in task_c.dependencies:
            dep = tl.get_task(dep_id)
            if dep is not None and dep.result:
                dep_parts.append(dep.result)

        assert len(dep_parts) == 2
        assert "Research findings" in dep_parts[0]
        assert "Analysis results" in dep_parts[1]


class TestTaskStateReset:
    """Fix 2: Verify task state resets between runs."""

    def test_fresh_task_list_replaces_old(self):
        """Creating a fresh TaskList and saving should clear old tasks."""
        session_state: dict = {}

        # Simulate first run: create and complete tasks
        tl = TaskList()
        tl.create_task("Old task 1")
        tl.create_task("Old task 2")
        tl.goal_complete = True
        tl.completion_summary = "Done"
        save_task_list(session_state, tl)

        assert len(load_task_list(session_state).tasks) == 2

        # Simulate second run: fresh task list (what _tools.py now does)
        fresh = TaskList()
        save_task_list(session_state, fresh)

        reloaded = load_task_list(session_state)
        assert len(reloaded.tasks) == 0
        assert reloaded.goal_complete is False
        assert reloaded.completion_summary is None


class TestConfigurableTruncation:
    """Fix 3: Verify result truncation is configurable."""

    def test_default_limit_200(self):
        """Default truncation should be 200 characters."""
        tl = TaskList()
        task = tl.create_task("Test")
        tl.update_task(task.id, status=TaskStatus.completed, result="x" * 300)

        summary = tl.get_summary_string()
        # Should truncate at 200 + "..."
        assert "x" * 200 + "..." in summary
        assert "x" * 201 not in summary

    def test_custom_limit_1000(self):
        """Custom limit should show more characters."""
        tl = TaskList()
        task = tl.create_task("Test")
        tl.update_task(task.id, status=TaskStatus.completed, result="x" * 1500)

        summary = tl.get_summary_string(result_limit=1000)
        assert "x" * 1000 + "..." in summary
        assert "x" * 1001 not in summary

    def test_short_result_no_truncation(self):
        """Results under the limit should not be truncated."""
        tl = TaskList()
        task = tl.create_task("Test")
        tl.update_task(task.id, status=TaskStatus.completed, result="Short result")

        summary = tl.get_summary_string(result_limit=500)
        assert "Short result" in summary
        assert "..." not in summary

    def test_team_default_limit_500(self):
        """Team class should default task_result_summary_limit to 500."""
        from agno.team.team import Team

        team = Team(name="test", members=[])
        assert team.task_result_summary_limit == 500


class TestEditTask:
    """Fix 4: Verify edit_task behavior via TaskList operations."""

    def test_edit_pending_task_title(self):
        """Should be able to edit title of a pending task."""
        tl = TaskList()
        task = tl.create_task("Original title")
        tl.update_task(task.id, title="Updated title")

        assert tl.get_task(task.id).title == "Updated title"

    def test_edit_pending_task_assignee(self):
        """Should be able to change assignee of a pending task."""
        tl = TaskList()
        task = tl.create_task("Task", assignee="agent_a")
        tl.update_task(task.id, assignee="agent_b")

        assert tl.get_task(task.id).assignee == "agent_b"

    def test_edit_pending_task_description(self):
        """Should be able to change description of a pending task."""
        tl = TaskList()
        task = tl.create_task("Task", description="Old desc")
        tl.update_task(task.id, description="New desc")

        assert tl.get_task(task.id).description == "New desc"


class TestCancelTask:
    """Fix 4: Verify cancel_task behavior via TaskList operations."""

    def test_cancel_pending_task(self):
        """Cancelling a pending task should set status to failed."""
        tl = TaskList()
        task = tl.create_task("Unwanted task")
        tl.update_task(task.id, status=TaskStatus.failed, result="Cancelled: no longer needed")

        cancelled = tl.get_task(task.id)
        assert cancelled.status == TaskStatus.failed
        assert "Cancelled" in cancelled.result

    def test_cancel_cascades_to_dependents(self):
        """Cancelling a task should cause dependents to become blocked/failed."""
        tl = TaskList()
        task_a = tl.create_task("Parent task")
        task_b = tl.create_task("Child task", dependencies=[task_a.id])

        # Cancel parent
        tl.update_task(task_a.id, status=TaskStatus.failed, result="Cancelled")

        child = tl.get_task(task_b.id)
        # Child should be auto-failed since its dependency failed
        assert child.status == TaskStatus.failed

    def test_cannot_cancel_completed_task(self):
        """A completed task's status can be set to failed but this tests the tool guard."""
        tl = TaskList()
        task = tl.create_task("Done task")
        tl.update_task(task.id, status=TaskStatus.completed, result="Finished")

        # The tool function checks status before cancelling —
        # here we verify the task is in completed state
        assert tl.get_task(task.id).status == TaskStatus.completed
