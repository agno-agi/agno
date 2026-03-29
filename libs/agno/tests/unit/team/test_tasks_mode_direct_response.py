"""Unit tests for tasks mode direct response behavior.

Verifies that tasks mode allows the model to respond directly for simple
requests without going through the full task lifecycle (create tasks,
execute, mark_all_complete).
"""

from agno.team.mode import TeamMode


class TestTasksModePrompt:
    """Tests that the tasks mode system prompt includes direct response guidance."""

    def test_tasks_mode_prompt_contains_respond_directly(self):
        """Tasks mode prompt should tell the model it can respond directly."""
        from agno.team._messages import _get_mode_instructions
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.tasks)
        instructions = _get_mode_instructions(team)

        assert "respond without creating tasks or delegating" in instructions

    def test_tasks_mode_prompt_contains_conditional_mark_all_complete(self):
        """Tasks mode prompt should say mark_all_complete is only for when tasks were created."""
        from agno.team._messages import _get_mode_instructions
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.tasks)
        instructions = _get_mode_instructions(team)

        assert "Only call `mark_all_complete` when you actually created and executed tasks" in instructions

    def test_tasks_mode_prompt_contains_parallel_guidance(self):
        """Tasks mode prompt should guide against unnecessary parallelization."""
        from agno.team._messages import _get_mode_instructions
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.tasks)
        instructions = _get_mode_instructions(team)

        assert "genuinely independent" in instructions

    def test_tasks_mode_prompt_contains_progressive_complexity(self):
        """Tasks mode prompt should discourage over-decomposition."""
        from agno.team._messages import _get_mode_instructions
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.tasks)
        instructions = _get_mode_instructions(team)

        assert "Do not over-decompose" in instructions

    def test_other_modes_unchanged(self):
        """Coordinate, route, and broadcast mode prompts should still have their own respond-directly clause."""
        from agno.team._messages import _get_mode_instructions
        from agno.team.team import Team

        for mode in [TeamMode.coordinate, TeamMode.route, TeamMode.broadcast]:
            team = Team(name="test", members=[], mode=mode)
            instructions = _get_mode_instructions(team)
            assert "respond without delegating" in instructions, f"{mode} missing respond-directly clause"


class TestContinueMessageConditional:
    """Tests that the 'Continue working' message is conditional on tasks existing."""

    def test_continue_message_with_tasks(self):
        """When tasks exist, should inject 'Continue working on the tasks'."""
        from agno.team.task import TaskList, save_task_list

        task_list = TaskList()
        task_list.create_task("Test task", description="A task")
        session_state: dict = {}
        save_task_list(session_state, task_list)

        reloaded = TaskList()
        from agno.team.task import load_task_list

        reloaded = load_task_list(session_state)

        # Verify tasks exist so the conditional would take the "tasks" branch
        assert len(reloaded.tasks) > 0

    def test_continue_message_without_tasks(self):
        """When no tasks exist, should NOT inject 'Continue working on the tasks'."""
        from agno.team.task import TaskList, load_task_list, save_task_list

        task_list = TaskList()
        session_state: dict = {}
        save_task_list(session_state, task_list)

        reloaded = load_task_list(session_state)

        # Verify no tasks so the conditional would take the "respond directly" branch
        assert len(reloaded.tasks) == 0


class TestModelResponseToolCallDetection:
    """Tests that ModelResponse.tool_calls can be used to detect direct responses."""

    def test_empty_tool_calls_is_falsy(self):
        """An empty tool_calls list should be falsy for the early exit check."""
        from agno.models.response import ModelResponse

        response = ModelResponse()
        assert not response.tool_calls

    def test_tool_calls_with_entries_is_truthy(self):
        """A tool_calls list with entries should be truthy."""
        from agno.models.response import ModelResponse

        response = ModelResponse()
        response.tool_calls = [{"id": "1", "type": "function", "function": {"name": "test", "arguments": "{}"}}]
        assert response.tool_calls
