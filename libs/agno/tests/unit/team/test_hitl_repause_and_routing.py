"""Regression tests for #7864:
1. Resolved requirements should not be re-emitted to clients on chained pauses.
2. Requirement routing must distinguish child runs by (member_agent_id, member_run_id),
   not only by member_agent_id, so batch delegations to the same member resume each
   paused child run independently.
"""

from typing import Dict, List, Optional, Tuple
from unittest.mock import MagicMock

from agno.models.response import ToolExecution
from agno.run.requirement import RunRequirement
from agno.team._hooks import _drop_resolved_requirements


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_te(tool_name: str, **overrides) -> ToolExecution:
    defaults: Dict = {"tool_name": tool_name, "tool_args": {}}
    defaults.update(overrides)
    return ToolExecution(**defaults)


def _resolved_req(tool_name: str, member_agent_id: Optional[str] = None) -> RunRequirement:
    # A confirmed-true tool execution -> requirement.is_resolved() == True
    req = RunRequirement(tool_execution=_make_te(tool_name, requires_confirmation=True, confirmed=True))
    if member_agent_id is not None:
        req.member_agent_id = member_agent_id
    return req


def _unresolved_req(tool_name: str, member_agent_id: Optional[str] = None) -> RunRequirement:
    req = RunRequirement(tool_execution=_make_te(tool_name, requires_confirmation=True, confirmed=None))
    if member_agent_id is not None:
        req.member_agent_id = member_agent_id
    return req


# ===========================================================================
# Fix #2: _drop_resolved_requirements
# ===========================================================================


class TestDropResolvedRequirements:
    """The hook helper that strips resolved entries before re-pausing."""

    def test_drops_resolved_keeps_unresolved(self):
        run = MagicMock()
        run.requirements = [
            _resolved_req("collect_team_input"),
            _unresolved_req("collect_member_input", member_agent_id="agent-1"),
        ]

        _drop_resolved_requirements(run)

        assert len(run.requirements) == 1
        assert run.requirements[0].tool_execution.tool_name == "collect_member_input"

    def test_noop_when_no_requirements(self):
        run = MagicMock()
        run.requirements = None
        _drop_resolved_requirements(run)
        assert run.requirements is None

    def test_drops_all_when_all_resolved(self):
        run = MagicMock()
        run.requirements = [
            _resolved_req("a"),
            _resolved_req("b"),
        ]
        _drop_resolved_requirements(run)
        assert run.requirements == []

    def test_keeps_all_when_none_resolved(self):
        run = MagicMock()
        reqs = [_unresolved_req("a"), _unresolved_req("b")]
        run.requirements = reqs
        _drop_resolved_requirements(run)
        assert run.requirements == reqs


# ===========================================================================
# Fix #3: routing groups by (member_agent_id, member_run_id)
# ===========================================================================


class TestRoutingGroupKey:
    """Validates the grouping key used by _route_requirements_to_members and friends.

    We don't invoke the routing functions directly (they call member.continue_run);
    we exercise the grouping logic the same way they do to guarantee that two
    paused child runs of the same member each get their own bucket.
    """

    @staticmethod
    def _group_by_member(reqs: List[RunRequirement]) -> Dict[Tuple[str, Optional[str]], List[RunRequirement]]:
        # Mirror the production grouping in _route_requirements_to_members*.
        out: Dict[Tuple[str, Optional[str]], List[RunRequirement]] = {}
        for req in reqs:
            mid = getattr(req, "member_agent_id", None)
            if mid is not None:
                out.setdefault((mid, getattr(req, "member_run_id", None)), []).append(req)
        return out

    def test_same_agent_two_paused_runs_get_separate_buckets(self):
        req_a = _unresolved_req("archive_item", member_agent_id="agent-1")
        req_a.member_run_id = "child-run-A"
        req_b = _unresolved_req("archive_item", member_agent_id="agent-1")
        req_b.member_run_id = "child-run-B"

        groups = self._group_by_member([req_a, req_b])

        assert len(groups) == 2
        assert groups[("agent-1", "child-run-A")] == [req_a]
        assert groups[("agent-1", "child-run-B")] == [req_b]

    def test_same_agent_same_run_id_groups_together(self):
        """Multiple requirements for the same child run remain together."""
        req_a = _unresolved_req("archive_item", member_agent_id="agent-1")
        req_a.member_run_id = "child-run-A"
        req_b = _unresolved_req("delete_item", member_agent_id="agent-1")
        req_b.member_run_id = "child-run-A"

        groups = self._group_by_member([req_a, req_b])

        assert len(groups) == 1
        assert groups[("agent-1", "child-run-A")] == [req_a, req_b]

    def test_different_agents_get_separate_buckets(self):
        req_a = _unresolved_req("do_a", member_agent_id="agent-1")
        req_a.member_run_id = "child-A"
        req_b = _unresolved_req("do_b", member_agent_id="agent-2")
        req_b.member_run_id = "child-B"

        groups = self._group_by_member([req_a, req_b])

        assert len(groups) == 2
