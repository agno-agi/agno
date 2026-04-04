"""BUG-015: Reasoning always reports success=True even on failure.

The reasoning loop can break on 3+ failure conditions, but the final
ReasoningResult always has success=True hardcoded.
"""

import inspect
import re

import pytest


class TestBUG015ReasoningAlwaysSuccess:
    @pytest.fixture
    def manager_source(self):
        return inspect.getsource(__import__("agno.reasoning.manager", fromlist=["manager"]))

    def test_sync_final_yield_hardcodes_success_true(self, manager_source):
        """Verify sync run_default_reasoning always yields success=True."""
        sync_match = re.search(
            r"def run_default_reasoning\(.*?\n(?=\s+async def |\Z)",
            manager_source,
            re.DOTALL,
        )
        assert sync_match is not None
        sync_source = sync_match.group(0)

        final_yields = re.findall(r"ReasoningResult\([^)]*success=True[^)]*\)", sync_source, re.DOTALL)
        assert len(final_yields) >= 1, "Expected at least one hardcoded success=True in sync path"

    def test_sync_loop_has_break_on_errors(self, manager_source):
        """Verify the sync loop can break on multiple failure conditions."""
        sync_match = re.search(
            r"def run_default_reasoning\(.*?\n(?=\s+async def |\Z)",
            manager_source,
            re.DOTALL,
        )
        assert sync_match is not None
        sync_source = sync_match.group(0)

        breaks_after_error = re.findall(r"log_warning.*?break|log_error.*?break", sync_source, re.DOTALL)
        assert len(breaks_after_error) >= 2, f"Expected at least 2 error+break paths, found {len(breaks_after_error)}"

    def test_no_success_false_in_loop(self, manager_source):
        """Verify no variable tracks failure state in the loop."""
        sync_match = re.search(
            r"def run_default_reasoning\(.*?\n(?=\s+async def |\Z)",
            manager_source,
            re.DOTALL,
        )
        assert sync_match is not None
        sync_source = sync_match.group(0)

        has_failure_tracking = "reasoning_succeeded" in sync_source or "success = False" in sync_source
        assert not has_failure_tracking, "Bug already fixed — failure tracking now exists"

    def test_async_has_same_pattern(self, manager_source):
        """Verify async arun_default_reasoning has the same hardcoded success=True."""
        async_match = re.search(
            r"async def arun_default_reasoning\(.*?\n(?=\s+(?:async )?def |\Z)",
            manager_source,
            re.DOTALL,
        )
        assert async_match is not None
        async_source = async_match.group(0)

        final_yields = re.findall(r"ReasoningResult\([^)]*success=True[^)]*\)", async_source, re.DOTALL)
        assert len(final_yields) >= 1, "Expected hardcoded success=True in async path too"

    def test_native_reasoning_uses_success_false(self, manager_source):
        """Control: native reasoning correctly uses success=False on errors."""
        has_success_false = re.findall(r"ReasoningResult\([^)]*success=False[^)]*\)", manager_source, re.DOTALL)
        assert len(has_success_false) >= 1, "Expected at least one success=False in native reasoning paths"
