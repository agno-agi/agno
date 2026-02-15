"""BUG-019: Team sync hooks missing iscoroutinefunction check.

Agent sync hooks correctly check for async functions and skip them.
Team sync hooks call them directly, returning an unawaited coroutine.
"""

import inspect
import re

import pytest


class TestBUG019TeamSyncHooksMissingCheck:
    @pytest.fixture
    def team_hooks_source(self):
        return inspect.getsource(__import__("agno.team._hooks", fromlist=["_hooks"]))

    @pytest.fixture
    def agent_hooks_source(self):
        return inspect.getsource(__import__("agno.agent._hooks", fromlist=["_hooks"]))

    def test_agent_sync_pre_hooks_has_check(self, agent_hooks_source):
        """Control: agent execute_pre_hooks has iscoroutinefunction check."""
        pre_hooks_match = re.search(
            r"def execute_pre_hooks\(.*?\n(?=\ndef |\nasync def |\Z)",
            agent_hooks_source,
            re.DOTALL,
        )
        assert pre_hooks_match is not None
        source = pre_hooks_match.group(0)
        assert "iscoroutinefunction" in source, "Agent sync pre_hooks should check for async hooks"

    def test_team_sync_pre_hooks_missing_check(self, team_hooks_source):
        """BUG: team _execute_pre_hooks does NOT have iscoroutinefunction check."""
        pre_hooks_match = re.search(
            r"def _execute_pre_hooks\(.*?\n(?=\ndef |\nasync def |\Z)",
            team_hooks_source,
            re.DOTALL,
        )
        assert pre_hooks_match is not None
        source = pre_hooks_match.group(0)
        assert "iscoroutinefunction" not in source, "Bug already fixed — team sync pre_hooks now checks"

    def test_team_sync_post_hooks_missing_check(self, team_hooks_source):
        """BUG: team _execute_post_hooks does NOT have iscoroutinefunction check."""
        post_hooks_match = re.search(
            r"def _execute_post_hooks\(.*?\n(?=\ndef |\nasync def |\Z)",
            team_hooks_source,
            re.DOTALL,
        )
        assert post_hooks_match is not None
        source = post_hooks_match.group(0)
        assert "iscoroutinefunction" not in source, "Bug already fixed — team sync post_hooks now checks"

    def test_async_hook_returns_coroutine_without_await(self):
        """Prove that calling an async function without await returns a coroutine."""
        import asyncio
        import warnings

        async def my_async_hook(**kwargs):
            return "executed"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = my_async_hook(run_input="test")

        assert asyncio.iscoroutine(result), "Calling async func without await should return coroutine"
        result.close()

    def test_team_async_pre_hooks_has_check(self, team_hooks_source):
        """Control: team _aexecute_pre_hooks HAS iscoroutinefunction check."""
        async_pre_match = re.search(
            r"async def _aexecute_pre_hooks\(.*?\n(?=\ndef |\nasync def |\Z)",
            team_hooks_source,
            re.DOTALL,
        )
        assert async_pre_match is not None
        source = async_pre_match.group(0)
        assert "iscoroutinefunction" in source, "Async version should have the check"
