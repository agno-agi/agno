"""Tests for Team continue_run helpers (propagation, routing, normalization)."""

import asyncio
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.models.response import ToolExecution
from agno.run import RunStatus
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_execution(**overrides) -> ToolExecution:
    defaults = dict(tool_name="do_something", tool_args={"x": 1})
    defaults.update(overrides)
    return ToolExecution(**defaults)


def _make_requirement(**te_overrides) -> RunRequirement:
    return RunRequirement(tool_execution=_make_tool_execution(**te_overrides))


# ===========================================================================
# 1. _propagate_member_pause
# ===========================================================================


class TestPropagateMemberPause:
    def test_copies_requirements_with_member_context(self):
        from agno.team._tools import _propagate_member_pause

        # Create a mock member agent
        member_agent = MagicMock()
        member_agent.name = "Research Agent"

        # Create a member run response with requirements
        member_run_response = MagicMock()
        req = _make_requirement(requires_confirmation=True)
        member_run_response.requirements = [req]
        member_run_response.run_id = "member-run-123"

        # Create team run response
        run_response = MagicMock()
        run_response.requirements = None

        with patch("agno.team._tools.get_member_id", return_value="member-id-abc"):
            _propagate_member_pause(run_response, member_agent, member_run_response)

        assert run_response.requirements is not None
        assert len(run_response.requirements) == 1
        copied_req = run_response.requirements[0]
        assert copied_req.member_agent_id == "member-id-abc"
        assert copied_req.member_agent_name == "Research Agent"
        assert copied_req.member_run_id == "member-run-123"

    def test_deep_copies_requirements(self):
        """Modifying the copied requirement must not affect the original."""
        from agno.team._tools import _propagate_member_pause

        member_agent = MagicMock()
        member_agent.name = "Agent"

        req = _make_requirement(requires_confirmation=True)
        member_run_response = MagicMock()
        member_run_response.requirements = [req]
        member_run_response.run_id = "run-1"

        run_response = MagicMock()
        run_response.requirements = None

        with patch("agno.team._tools.get_member_id", return_value="id-1"):
            _propagate_member_pause(run_response, member_agent, member_run_response)

        # Modify the copied requirement
        run_response.requirements[0].member_agent_id = "changed"
        # Original should be unaffected
        assert req.member_agent_id is None

    def test_user_input_schema_is_deeply_copied(self):
        """Mutating the copied user_input_schema must not affect the original."""
        from agno.team._tools import _propagate_member_pause
        from agno.tools.function import UserInputField

        member_agent = MagicMock()
        member_agent.name = "Agent"

        req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="city", field_type=str)],
        )
        original_schema = req.tool_execution.user_input_schema
        member_run_response = MagicMock()
        member_run_response.requirements = [req]
        member_run_response.run_id = "run-1"

        run_response = MagicMock()
        run_response.requirements = None

        with patch("agno.team._tools.get_member_id", return_value="id-1"):
            _propagate_member_pause(run_response, member_agent, member_run_response)

        copied_req = run_response.requirements[0]
        # Mutate the copy's user_input_schema
        copied_req.user_input_schema[0].value = "Tokyo"
        # Original user_input_schema should be unaffected
        assert original_schema[0].value is None
        # The requirement-level schema should also be isolated
        assert req.user_input_schema[0].value is None

    def test_tool_execution_is_deeply_copied(self):
        """Mutating the copied tool_execution must not affect the original."""
        from agno.team._tools import _propagate_member_pause

        member_agent = MagicMock()
        member_agent.name = "Agent"

        req = _make_requirement(requires_confirmation=True)
        original_tool_execution = req.tool_execution
        member_run_response = MagicMock()
        member_run_response.requirements = [req]
        member_run_response.run_id = "run-1"

        run_response = MagicMock()
        run_response.requirements = None

        with patch("agno.team._tools.get_member_id", return_value="id-1"):
            _propagate_member_pause(run_response, member_agent, member_run_response)

        copied_req = run_response.requirements[0]
        # Mutate the copy's tool_execution
        copied_req.tool_execution.confirmed = True
        # Original tool_execution should be unaffected
        assert original_tool_execution.confirmed is None

    def test_empty_requirements_does_nothing(self):
        from agno.team._tools import _propagate_member_pause

        member_agent = MagicMock()
        member_run_response = MagicMock()
        member_run_response.requirements = []

        run_response = MagicMock()
        run_response.requirements = None

        _propagate_member_pause(run_response, member_agent, member_run_response)
        # requirements should stay None since nothing was added
        assert run_response.requirements is None

    def test_multiple_requirements_all_copied(self):
        from agno.team._tools import _propagate_member_pause

        member_agent = MagicMock()
        member_agent.name = "Agent"

        req1 = _make_requirement(requires_confirmation=True)
        req2 = _make_requirement(external_execution_required=True)
        member_run_response = MagicMock()
        member_run_response.requirements = [req1, req2]
        member_run_response.run_id = "run-1"

        run_response = MagicMock()
        run_response.requirements = None

        with patch("agno.team._tools.get_member_id", return_value="id-1"):
            _propagate_member_pause(run_response, member_agent, member_run_response)

        assert len(run_response.requirements) == 2
        assert all(r.member_agent_id == "id-1" for r in run_response.requirements)

    def test_appends_to_existing_requirements(self):
        from agno.team._tools import _propagate_member_pause

        member_agent = MagicMock()
        member_agent.name = "Agent"

        new_req = _make_requirement(requires_confirmation=True)
        member_run_response = MagicMock()
        member_run_response.requirements = [new_req]
        member_run_response.run_id = "run-1"

        existing_req = _make_requirement(external_execution_required=True)
        run_response = MagicMock()
        run_response.requirements = [existing_req]

        with patch("agno.team._tools.get_member_id", return_value="id-1"):
            _propagate_member_pause(run_response, member_agent, member_run_response)

        assert len(run_response.requirements) == 2


# ===========================================================================
# 2. _find_member_route_by_id
# ===========================================================================


class TestFindMemberRouteById:
    def _make_team_with_members(self):
        """Create a team hierarchy for testing."""
        from agno.agent import Agent
        from agno.team.team import Team

        agent_a = Agent(name="Agent A")
        agent_b = Agent(name="Agent B")
        agent_c = Agent(name="Agent C")

        sub_team = Team(name="Sub Team", members=[agent_c])
        team = Team(name="Parent Team", members=[agent_a, agent_b, sub_team])

        return team, agent_a, agent_b, agent_c, sub_team

    def test_direct_member_match(self):
        from agno.team._tools import _find_member_route_by_id
        from agno.utils.team import get_member_id

        team, agent_a, _, _, _ = self._make_team_with_members()
        member_id = get_member_id(agent_a)

        result = _find_member_route_by_id(team, member_id)
        assert result is not None
        idx, member = result
        assert idx == 0
        assert member is agent_a

    def test_nested_member_returns_sub_team(self):
        """For a member nested inside a sub-team, should return the sub-team for routing."""
        from agno.team._tools import _find_member_route_by_id
        from agno.utils.team import get_member_id

        team, _, _, agent_c, sub_team = self._make_team_with_members()
        member_id = get_member_id(agent_c)

        result = _find_member_route_by_id(team, member_id)
        assert result is not None
        idx, member = result
        assert idx == 2  # sub_team is at index 2
        assert member is sub_team  # Routes through sub-team, not directly to agent_c

    def test_unknown_member_returns_none(self):
        from agno.team._tools import _find_member_route_by_id

        team, _, _, _, _ = self._make_team_with_members()
        result = _find_member_route_by_id(team, "nonexistent-id")
        assert result is None


# ===========================================================================
# 3. _normalize_requirements_payload
# ===========================================================================


class TestNormalizeRequirementsPayload:
    def test_converts_dict_to_run_requirement(self):
        from agno.team._run import _normalize_requirements_payload

        req = _make_requirement(requires_confirmation=True)
        d = req.to_dict()

        result = _normalize_requirements_payload([d])
        assert len(result) == 1
        assert isinstance(result[0], RunRequirement)

    def test_passes_through_run_requirement_objects(self):
        from agno.team._run import _normalize_requirements_payload

        req = _make_requirement(requires_confirmation=True)
        result = _normalize_requirements_payload([req])
        assert result[0] is req  # Same object, not a copy

    def test_handles_mixed_list(self):
        from agno.team._run import _normalize_requirements_payload

        req = _make_requirement(requires_confirmation=True)
        d = _make_requirement(external_execution_required=True).to_dict()

        result = _normalize_requirements_payload([req, d])
        assert len(result) == 2
        assert isinstance(result[0], RunRequirement)
        assert isinstance(result[1], RunRequirement)


# ===========================================================================
# 4. _has_member_requirements and _has_team_level_requirements
# ===========================================================================


class TestRequirementClassification:
    def test_has_member_requirements(self):
        from agno.team._run import _has_member_requirements

        req = _make_requirement(requires_confirmation=True)
        req.member_agent_id = "agent-1"
        assert _has_member_requirements([req]) is True

    def test_has_no_member_requirements(self):
        from agno.team._run import _has_member_requirements

        req = _make_requirement(requires_confirmation=True)
        assert _has_member_requirements([req]) is False

    def test_has_team_level_requirements(self):
        from agno.team._run import _has_team_level_requirements

        req = _make_requirement(requires_confirmation=True)
        # No member_agent_id means it's a team-level requirement
        assert _has_team_level_requirements([req]) is True

    def test_has_no_team_level_requirements(self):
        from agno.team._run import _has_team_level_requirements

        req = _make_requirement(requires_confirmation=True)
        req.member_agent_id = "agent-1"
        assert _has_team_level_requirements([req]) is False

    def test_mixed_requirements(self):
        from agno.team._run import _has_member_requirements, _has_team_level_requirements

        team_req = _make_requirement(requires_confirmation=True)
        member_req = _make_requirement(external_execution_required=True)
        member_req.member_agent_id = "agent-1"

        reqs = [team_req, member_req]
        assert _has_member_requirements(reqs) is True
        assert _has_team_level_requirements(reqs) is True

    def test_empty_list(self):
        from agno.team._run import _has_member_requirements, _has_team_level_requirements

        assert _has_member_requirements([]) is False
        assert _has_team_level_requirements([]) is False


# ===========================================================================
# 5. _build_continuation_message
# ===========================================================================


class TestBuildContinuationMessage:
    def test_empty_results(self):
        from agno.team._run import _build_continuation_message

        msg = _build_continuation_message([])
        assert "completed" in msg.lower()

    def test_single_result(self):
        from agno.team._run import _build_continuation_message

        msg = _build_continuation_message(["[Agent A]: Deployment successful"])
        assert "Agent A" in msg
        assert "Deployment successful" in msg

    def test_multiple_results(self):
        from agno.team._run import _build_continuation_message

        msg = _build_continuation_message(
            [
                "[Agent A]: Result 1",
                "[Agent B]: Result 2",
            ]
        )
        assert "Agent A" in msg
        assert "Agent B" in msg
        assert "Result 1" in msg
        assert "Result 2" in msg


# ===========================================================================
# 6. Chained HITL: newly propagated requirements are preserved
# ===========================================================================


class TestChainedHITLRequirements:
    """Verify that after routing, newly propagated requirements from chained
    HITL (member pausing again) are merged back with team-level requirements
    rather than being discarded."""

    def test_newly_propagated_reqs_preserved_after_routing(self):
        """Simulate: member routing propagates new reqs back onto run_response.
        After the routing block, those new reqs must appear alongside team-level reqs."""
        # Set up initial state: one team-level req and one member req
        team_req = _make_requirement(requires_confirmation=True)
        member_req = _make_requirement(external_execution_required=True)
        member_req.member_agent_id = "agent-1"
        member_req.member_agent_name = "Agent 1"

        all_reqs = [team_req, member_req]

        # Simulate the routing logic from continue_run_dispatch
        member_reqs = [r for r in all_reqs if getattr(r, "member_agent_id", None) is not None]
        team_level_reqs = [r for r in all_reqs if getattr(r, "member_agent_id", None) is None]

        original_member_req_ids = {id(r) for r in member_reqs}

        # Simulate _route_requirements_to_members appending a new propagated req
        new_propagated = _make_requirement(requires_confirmation=True)
        new_propagated.member_agent_id = "agent-2"
        simulated_post_routing = member_reqs + [new_propagated]

        # Merge logic
        newly_propagated = [r for r in simulated_post_routing if id(r) not in original_member_req_ids]
        final_reqs = team_level_reqs + newly_propagated

        assert len(final_reqs) == 2  # team_req + new_propagated
        assert team_req in final_reqs
        assert new_propagated in final_reqs
        # Original member_req should NOT be in the final set
        assert member_req not in final_reqs

    def test_no_propagated_reqs_yields_only_team_level(self):
        """If no member pauses again, only team-level reqs remain."""
        team_req = _make_requirement(requires_confirmation=True)
        member_req = _make_requirement(external_execution_required=True)
        member_req.member_agent_id = "agent-1"

        all_reqs = [team_req, member_req]
        member_reqs = [r for r in all_reqs if getattr(r, "member_agent_id", None) is not None]
        team_level_reqs = [r for r in all_reqs if getattr(r, "member_agent_id", None) is None]

        original_member_req_ids = {id(r) for r in member_reqs}
        # Simulate routing consuming all member reqs (no new propagation)
        simulated_post_routing = member_reqs

        newly_propagated = [r for r in simulated_post_routing if id(r) not in original_member_req_ids]
        final_reqs = team_level_reqs + newly_propagated

        assert len(final_reqs) == 1
        assert final_reqs[0] is team_req


# ===========================================================================
# 7. Mixed HITL types
# ===========================================================================


class TestMixedHITLTypes:
    """Verify requirements of different HITL types can coexist."""

    def test_mixed_confirmation_and_external_execution(self):
        conf_req = _make_requirement(requires_confirmation=True)
        ext_req = _make_requirement(external_execution_required=True)

        assert conf_req.needs_confirmation is True
        assert conf_req.needs_external_execution is False
        assert ext_req.needs_confirmation is False
        assert ext_req.needs_external_execution is True

        # Both should be unresolved
        assert conf_req.is_resolved() is False
        assert ext_req.is_resolved() is False

        # Resolve confirmation
        conf_req.confirm()
        assert conf_req.is_resolved() is True
        # ext_req still unresolved
        assert ext_req.is_resolved() is False

        # Resolve external execution
        ext_req.set_external_execution_result("done")
        assert ext_req.is_resolved() is True

    def test_mixed_member_and_team_level_requirements(self):
        from agno.team._run import _has_member_requirements, _has_team_level_requirements

        team_conf_req = _make_requirement(requires_confirmation=True)
        member_ext_req = _make_requirement(external_execution_required=True)
        member_ext_req.member_agent_id = "agent-1"

        from agno.tools.function import UserInputField

        member_input_req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="city", field_type=str)],
        )
        member_input_req.member_agent_id = "agent-2"

        reqs = [team_conf_req, member_ext_req, member_input_req]

        assert _has_member_requirements(reqs) is True
        assert _has_team_level_requirements(reqs) is True

        # Categorize
        team_reqs = [r for r in reqs if getattr(r, "member_agent_id", None) is None]
        member_reqs = [r for r in reqs if getattr(r, "member_agent_id", None) is not None]
        assert len(team_reqs) == 1
        assert len(member_reqs) == 2


# ===========================================================================
# 8. Deeply nested teams (3+ levels)
# ===========================================================================


class TestDeeplyNestedTeams:
    """Test _find_member_route_by_id with 3+ levels of nesting."""

    def test_three_level_nesting_returns_top_sub_team(self):
        from agno.agent import Agent
        from agno.team._tools import _find_member_route_by_id
        from agno.team.team import Team
        from agno.utils.team import get_member_id

        deep_agent = Agent(name="Deep Agent")
        inner_team = Team(name="Inner Team", members=[deep_agent])
        outer_team = Team(name="Outer Team", members=[inner_team])
        root_team = Team(name="Root Team", members=[outer_team])

        deep_agent_id = get_member_id(deep_agent)

        result = _find_member_route_by_id(root_team, deep_agent_id)
        assert result is not None
        idx, member = result
        # Should return outer_team (the direct child of root_team)
        assert member is outer_team
        assert idx == 0

    def test_three_level_nesting_direct_child_match(self):
        from agno.agent import Agent
        from agno.team._tools import _find_member_route_by_id
        from agno.team.team import Team
        from agno.utils.team import get_member_id

        deep_agent = Agent(name="Deep Agent")
        inner_team = Team(name="Inner Team", members=[deep_agent])
        mid_agent = Agent(name="Mid Agent")
        outer_team = Team(name="Outer Team", members=[inner_team, mid_agent])
        root_team = Team(name="Root Team", members=[outer_team])

        mid_agent_id = get_member_id(mid_agent)

        # mid_agent is inside outer_team, so routing should go through outer_team
        result = _find_member_route_by_id(root_team, mid_agent_id)
        assert result is not None
        idx, member = result
        assert member is outer_team

    def test_deeply_nested_unknown_returns_none(self):
        from agno.agent import Agent
        from agno.team._tools import _find_member_route_by_id
        from agno.team.team import Team

        deep_agent = Agent(name="Deep Agent")
        inner_team = Team(name="Inner Team", members=[deep_agent])
        outer_team = Team(name="Outer Team", members=[inner_team])

        result = _find_member_route_by_id(outer_team, "nonexistent-deep-id")
        assert result is None


# ===========================================================================
# 9. _member_run_response cleanup
# ===========================================================================


class TestMemberRunResponseCleanup:
    """Verify that _member_run_response is cleared after routing consumption."""

    def test_propagate_sets_member_run_response(self):
        from agno.team._tools import _propagate_member_pause

        member_agent = MagicMock()
        member_agent.name = "Agent"

        member_run_response = MagicMock()
        req = _make_requirement(requires_confirmation=True)
        member_run_response.requirements = [req]
        member_run_response.run_id = "run-1"

        run_response = MagicMock()
        run_response.requirements = None

        with patch("agno.team._tools.get_member_id", return_value="id-1"):
            _propagate_member_pause(run_response, member_agent, member_run_response)

        # _member_run_response should be set
        assert run_response.requirements[0]._member_run_response is member_run_response


# ===========================================================================
# 10. Unresolved team-level requirements guard
# ===========================================================================


class TestUnresolvedTeamLevelRequirements:
    """Verify that unresolved team-level requirements are detected properly
    for the re-pause guard in continue_run_dispatch."""

    def test_unresolved_team_level_detected(self):
        """Unresolved team-level requirement should be found by the guard."""
        req = _make_requirement(requires_confirmation=True)
        # No member_agent_id means team-level
        assert req.member_agent_id is None
        assert not req.is_resolved()

        unresolved = [r for r in [req] if getattr(r, "member_agent_id", None) is None and not r.is_resolved()]
        assert len(unresolved) == 1

    def test_resolved_team_level_not_detected(self):
        """Resolved team-level requirement should not trigger the guard."""
        req = _make_requirement(requires_confirmation=True)
        req.confirm()
        assert req.is_resolved()

        unresolved = [r for r in [req] if getattr(r, "member_agent_id", None) is None and not r.is_resolved()]
        assert len(unresolved) == 0

    def test_member_reqs_excluded_from_team_level_guard(self):
        """Member requirements should not be caught by the team-level guard."""
        req = _make_requirement(requires_confirmation=True)
        req.member_agent_id = "agent-1"

        unresolved = [r for r in [req] if getattr(r, "member_agent_id", None) is None and not r.is_resolved()]
        assert len(unresolved) == 0

    def test_mixed_reqs_only_team_level_unresolved(self):
        """Only unresolved team-level requirements should trigger the guard."""
        team_unresolved = _make_requirement(requires_confirmation=True)
        team_resolved = _make_requirement(requires_confirmation=True)
        team_resolved.confirm()
        member_unresolved = _make_requirement(requires_confirmation=True)
        member_unresolved.member_agent_id = "agent-1"

        all_reqs = [team_unresolved, team_resolved, member_unresolved]
        unresolved = [r for r in all_reqs if getattr(r, "member_agent_id", None) is None and not r.is_resolved()]
        assert len(unresolved) == 1
        assert unresolved[0] is team_unresolved


# ===========================================================================
# 11. asyncio.gather error handling in _aroute_requirements_to_members
# ===========================================================================


class TestAsyncGatherErrorHandling:
    """Verify that _aroute_requirements_to_members handles member failures gracefully."""

    def test_gather_filters_exceptions(self):
        """When asyncio.gather returns exceptions, they should be filtered out."""
        # Simulate the post-gather filtering logic
        results = ["[Agent A]: Success", Exception("Agent B failed"), None, "[Agent C]: Done"]

        member_results = []
        for r in results:
            if isinstance(r, Exception):
                pass  # logged as warning
            elif r is not None:
                member_results.append(r)

        assert len(member_results) == 2
        assert member_results[0] == "[Agent A]: Success"
        assert member_results[1] == "[Agent C]: Done"

    def test_all_exceptions_yields_empty_results(self):
        """When all members fail, result list should be empty."""
        results = [Exception("fail 1"), Exception("fail 2")]

        member_results = []
        for r in results:
            if isinstance(r, Exception):
                pass
            elif r is not None:
                member_results.append(r)

        assert len(member_results) == 0


# ===========================================================================
# 12. _tool_result_requires_human_input
# ===========================================================================


class TestToolResultRequiresHumanInput:
    def test_matching_string(self):
        from agno.team._run import _tool_result_requires_human_input

        tool = _make_tool_execution(result="Tool requires human input to proceed")
        assert _tool_result_requires_human_input(tool) is True

    def test_case_insensitive(self):
        from agno.team._run import _tool_result_requires_human_input

        tool = _make_tool_execution(result="REQUIRES HUMAN INPUT")
        assert _tool_result_requires_human_input(tool) is True

    def test_no_match(self):
        from agno.team._run import _tool_result_requires_human_input

        tool = _make_tool_execution(result="Success: operation completed")
        assert _tool_result_requires_human_input(tool) is False

    def test_none_result(self):
        from agno.team._run import _tool_result_requires_human_input

        tool = _make_tool_execution(result=None)
        assert _tool_result_requires_human_input(tool) is False

    def test_non_string_result(self):
        from agno.team._run import _tool_result_requires_human_input

        tool = _make_tool_execution(result={"key": "requires human input"})
        assert _tool_result_requires_human_input(tool) is False


# ===========================================================================
# 13. _prepare_member_hitl_continuation improvements
# ===========================================================================


class TestPrepareMemberHitlContinuation:
    """Tests for the improved _prepare_member_hitl_continuation that handles
    delegate_task_to_members (plural) and case-insensitive matching."""

    def _make_run_response_with_tools(self, tools):
        run_response = MagicMock()
        run_response.tools = tools
        run_response.requirements = None
        return run_response

    def _make_run_messages(self, tool_call_ids):
        msgs = []
        for tc_id in tool_call_ids:
            msg = MagicMock()
            msg.role = "tool"
            msg.tool_call_id = tc_id
            msg.content = "requires human input"
            msgs.append(msg)
        run_messages = MagicMock()
        run_messages.messages = msgs
        return run_messages

    def test_updates_delegate_task_to_member(self):
        from agno.team._run import _prepare_member_hitl_continuation

        tool = _make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_call_id="tc-1",
            result="Tool requires human input",
        )
        run_response = self._make_run_response_with_tools([tool])
        run_messages = self._make_run_messages(["tc-1"])

        _prepare_member_hitl_continuation(run_response, run_messages, ["[Agent]: Done"])

        assert "requires human input" not in tool.result
        assert "Done" in tool.result

    def test_updates_delegate_task_to_members_plural(self):
        from agno.team._run import _prepare_member_hitl_continuation

        tool = _make_tool_execution(
            tool_name="delegate_task_to_members",
            tool_call_id="tc-1",
            result="Tool requires human input",
        )
        run_response = self._make_run_response_with_tools([tool])
        run_messages = self._make_run_messages(["tc-1"])

        _prepare_member_hitl_continuation(run_response, run_messages, ["[Agent]: Done"])

        assert "Done" in tool.result

    def test_updates_multiple_matching_tools(self):
        from agno.team._run import _prepare_member_hitl_continuation

        tool1 = _make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_call_id="tc-1",
            result="requires human input",
        )
        tool2 = _make_tool_execution(
            tool_name="delegate_task_to_members",
            tool_call_id="tc-2",
            result="requires human input",
        )
        run_response = self._make_run_response_with_tools([tool1, tool2])
        run_messages = self._make_run_messages(["tc-1", "tc-2"])

        _prepare_member_hitl_continuation(run_response, run_messages, ["[Agent]: Done"])

        assert "Done" in tool1.result
        assert "Done" in tool2.result
        assert run_messages.messages[0].content == run_messages.messages[1].content

    def test_falls_back_to_any_tool_with_human_input(self):
        """If no delegate tool matches, falls back to any tool with human input result."""
        from agno.team._run import _prepare_member_hitl_continuation

        tool = _make_tool_execution(
            tool_name="some_other_tool",
            tool_call_id="tc-1",
            result="requires human input",
        )
        run_response = self._make_run_response_with_tools([tool])
        run_messages = self._make_run_messages(["tc-1"])

        _prepare_member_hitl_continuation(run_response, run_messages, ["[Agent]: Done"])

        assert "Done" in tool.result

    def test_resets_run_state(self):
        from agno.team._run import _prepare_member_hitl_continuation

        tool = _make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_call_id="tc-1",
            result="requires human input",
        )
        run_response = self._make_run_response_with_tools([tool])
        run_response.status = RunStatus.paused
        run_response.content = "old content"
        run_messages = self._make_run_messages(["tc-1"])

        _prepare_member_hitl_continuation(run_response, run_messages, ["[Agent]: Done"])

        assert run_response.status == RunStatus.running
        assert run_response.content is None


# ===========================================================================
# 14. Approval resolution fallback in continue_run_dispatch
# ===========================================================================


class TestContinueRunApprovalResolution:
    def test_continue_run_dispatch_uses_resolved_admin_approval_without_requirements(self):
        from agno.team._run import continue_run_dispatch

        team = MagicMock()
        team.session_id = None
        team.add_history_to_context = False
        team.parser_model = None
        team.initialize_team = MagicMock()
        team.db = MagicMock()

        tool = _make_tool_execution(
            tool_call_id="tool-1",
            approval_type="required",
            requires_confirmation=True,
        )
        requirement = RunRequirement(tool)
        run_response = TeamRunOutput(
            run_id="run-1",
            session_id="session-1",
            requirements=[requirement],
            tools=[tool],
        )

        opts = SimpleNamespace(
            stream=False,
            stream_events=False,
            yield_run_output=False,
            dependencies=None,
            knowledge_filters=None,
            metadata=None,
        )
        team_session = MagicMock()
        team_session.runs = [run_response]
        sentinel = object()

        def _resolve_approval(db, run_id, paused_run_response):
            paused_run_response.requirements[0].confirm()

        with (
            patch("agno.team._init._has_async_db", return_value=False),
            patch("agno.team._init._initialize_session", return_value=("session-1", None)),
            patch("agno.team._storage._read_or_create_session", return_value=team_session),
            patch("agno.team._storage._update_metadata"),
            patch("agno.team._storage._load_session_state", return_value={}),
            patch("agno.team._run_options.resolve_run_options", return_value=opts),
            patch("agno.team._response.get_response_format", return_value=None),
            patch("agno.team._tools._determine_tools_for_model", return_value=[]),
            patch("agno.team._run._get_continue_run_messages", return_value=MagicMock(messages=[])),
            patch("agno.team._run._handle_team_tool_call_updates"),
            patch("agno.team._run._continue_run", return_value=sentinel) as mock_continue,
            patch("agno.run.approval.check_and_apply_approval_resolution", side_effect=_resolve_approval) as mock_apply,
        ):
            result = continue_run_dispatch(
                team,
                run_id="run-1",
                session_id="session-1",
                stream=False,
            )

        assert result is sentinel
        mock_apply.assert_called_once_with(team.db, "run-1", run_response)
        mock_continue.assert_called_once()

    def test_acontinue_run_uses_resolved_admin_approval_without_requirements(self):
        from agno.team._run import _acontinue_run

        team = MagicMock()
        team.retries = 0
        team.add_history_to_context = False
        team.events_to_skip = []
        team.store_events = False
        team.db = MagicMock()
        team.model = MagicMock()

        tool = _make_tool_execution(
            tool_call_id="tool-1",
            approval_type="required",
            requires_confirmation=True,
        )
        requirement = RunRequirement(tool)
        run_response = TeamRunOutput(
            run_id="run-1",
            session_id="session-1",
            requirements=[requirement],
            tools=[tool],
        )

        team_session = MagicMock()
        team_session.runs = [run_response]
        run_context = MagicMock()
        sentinel = object()

        async def _resolve_approval(db, run_id, paused_run_response):
            paused_run_response.requirements[0].confirm()

        async def _exercise():
            with (
                patch("agno.team._run._asetup_session", new=AsyncMock(return_value=team_session)),
                patch("agno.team._run.aregister_run", new=AsyncMock()),
                patch("agno.team._run.acleanup_run", new=AsyncMock()),
                patch("agno.team._init._disconnect_connectable_tools"),
                patch("agno.team._init._disconnect_mcp_tools", new=AsyncMock()),
                patch("agno.team._tools._check_and_refresh_mcp_tools", new=AsyncMock()),
                patch("agno.team._tools._aget_learning_tools", new=AsyncMock(return_value=[])),
                patch("agno.team._tools._determine_tools_for_model", return_value=[]),
                patch("agno.team._run._get_continue_run_messages", return_value=MagicMock(messages=[])),
                patch("agno.team._run._ahandle_team_tool_call_updates", new=AsyncMock()),
                patch("agno.team._run._ahandle_model_response_for_continue", new=AsyncMock(return_value=sentinel)),
                patch(
                    "agno.run.approval.acheck_and_apply_approval_resolution",
                    side_effect=_resolve_approval,
                ) as mock_apply,
            ):
                result = await _acontinue_run(
                    team,
                    session_id="session-1",
                    run_context=run_context,
                    run_id="run-1",
                    requirements=None,
                )

            assert result is sentinel
            mock_apply.assert_called_once_with(team.db, "run-1", run_response)

        asyncio.run(_exercise())

    def test_acontinue_run_stream_uses_run_id_for_empty_requirements(self):
        from agno.team._run import _acontinue_run_stream

        team = MagicMock()
        team.retries = 0
        team.events_to_skip = []
        team.store_events = False
        team.db = MagicMock()

        tool = _make_tool_execution(
            tool_call_id="tool-1",
            approval_type="required",
            requires_confirmation=True,
        )
        requirement = RunRequirement(tool)
        run_response = TeamRunOutput(
            run_id="run-1",
            session_id="session-1",
            requirements=[requirement],
            tools=[tool],
        )

        team_session = MagicMock()
        team_session.runs = [run_response]
        run_context = MagicMock()

        async def _pause_stream(*args, **kwargs):
            yield "paused-event"

        async def _exercise():
            with (
                patch("agno.team._run._asetup_session", new=AsyncMock(return_value=team_session)),
                patch("agno.team._run.aregister_run", new=AsyncMock()),
                patch("agno.team._run.acleanup_run", new=AsyncMock()),
                patch("agno.team._init._disconnect_connectable_tools"),
                patch("agno.team._init._disconnect_mcp_tools", new=AsyncMock()),
                patch(
                    "agno.run.approval.acheck_and_apply_approval_resolution",
                    new=AsyncMock(),
                ) as mock_apply,
                patch("agno.team._hooks.ahandle_team_run_paused_stream", side_effect=_pause_stream),
            ):
                events = []
                async for event in _acontinue_run_stream(
                    team,
                    session_id="session-1",
                    run_context=run_context,
                    run_id="run-1",
                    requirements=None,
                ):
                    events.append(event)

            assert events == ["paused-event"]
            mock_apply.assert_called_once_with(team.db, "run-1", run_response)

        asyncio.run(_exercise())


# ===========================================================================
# 15. respond_directly member continuation
# ===========================================================================


class TestRespondDirectlyMemberContinuation:
    cancellation = "Tool execution cancelled by the user: operation not approved."

    def _make_case(self, *, respond_directly=True):
        tool = _make_tool_execution(
            tool_call_id="member-tool-1",
            requires_confirmation=True,
        )
        requirement = RunRequirement(tool)
        requirement.member_agent_id = "member-id-1"
        requirement.member_agent_name = "Member 1"
        requirement.member_run_id = "member-run-1"
        requirement.reject("Not approved")

        delegate_tool = _make_tool_execution(
            tool_call_id="delegate-tool-1",
            tool_name="delegate_task_to_member",
            result="Member requires human input",
        )

        member_run_output = MagicMock()
        member_run_output.run_id = "member-run-1"
        member_run_output.tools = [tool]
        requirement._member_run_response = member_run_output

        member_response = MagicMock()
        member_response.is_paused = False
        member_response.content = self.cancellation
        member_response.content_type = "str"

        member = MagicMock()
        member.name = "Member 1"
        member.continue_run = MagicMock(return_value=member_response)
        member.acontinue_run = AsyncMock(return_value=member_response)

        run_response = TeamRunOutput(
            run_id="team-run-1",
            session_id="session-1",
            status=RunStatus.paused,
            requirements=[requirement],
            tools=[delegate_tool],
            content="stale paused content",
        )

        team = MagicMock()
        team.id = "team-1"
        team.name = "Team 1"
        team.session_id = None
        team.add_history_to_context = False
        team.parser_model = None
        team.output_model = None
        team._member_response_model = None
        team.initialize_team = MagicMock()
        team.db = MagicMock()
        team.model = MagicMock()
        team.respond_directly = respond_directly
        team.determine_input_for_members = False
        team.post_hooks = None
        team.session_summary_manager = None
        team.events_to_skip = []
        team.store_events = False
        team.stream_member_events = False
        team.retries = 0
        team.exponential_backoff = False
        team.delay_between_retries = 0

        team_session = MagicMock()
        team_session.session_id = "session-1"
        team_session.runs = [run_response]

        return team, team_session, run_response, requirement, member, member_run_output, member_response

    @staticmethod
    def _sync_opts(*, stream=False, stream_events=False, yield_run_output=False):
        return SimpleNamespace(
            stream=stream,
            stream_events=stream_events,
            yield_run_output=yield_run_output,
            dependencies=None,
            knowledge_filters=None,
            metadata=None,
        )

    @contextmanager
    def _sync_dispatch_patches(self, session, member, member_run_output, requirement, opts):
        with ExitStack() as stack:
            stack.enter_context(patch("agno.team._init._has_async_db", return_value=False))
            stack.enter_context(patch("agno.team._init._initialize_session", return_value=("session-1", None)))
            stack.enter_context(patch("agno.team._storage._read_or_create_session", return_value=session))
            stack.enter_context(patch("agno.team._storage._update_metadata"))
            stack.enter_context(patch("agno.team._storage._load_session_state", return_value={}))
            stack.enter_context(patch("agno.team._run_options.resolve_run_options", return_value=opts))
            stack.enter_context(patch("agno.run.approval.check_and_apply_approval_resolution"))
            stack.enter_context(
                patch("agno.team._run._reclaim_own_requirements", side_effect=lambda _t, reqs, _rid: reqs)
            )
            stack.enter_context(
                patch(
                    "agno.team._run._group_requirements_for_continue",
                    return_value=[(member, member_run_output, [requirement])],
                )
            )
            stack.enter_context(patch("agno.team._run.register_member_run"))
            stack.enter_context(patch("agno.team._response.get_response_format", return_value=None))
            stack.enter_context(patch("agno.team._tools._determine_tools_for_model", return_value=[]))
            stack.enter_context(patch("agno.team._run._get_continue_run_messages", return_value=MagicMock(messages=[])))
            yield

    @contextmanager
    def _async_dispatch_patches(self, session, member, member_run_output, requirement):
        with ExitStack() as stack:
            stack.enter_context(patch("agno.team._run._asetup_session", new=AsyncMock(return_value=session)))
            stack.enter_context(patch("agno.run.approval.acheck_and_apply_approval_resolution", new=AsyncMock()))
            stack.enter_context(patch("agno.team._run.aregister_run", new=AsyncMock()))
            stack.enter_context(patch("agno.team._run.aregister_member_run", new=AsyncMock()))
            stack.enter_context(patch("agno.team._run.acleanup_run", new=AsyncMock()))
            stack.enter_context(patch("agno.team._init._disconnect_connectable_tools"))
            stack.enter_context(patch("agno.team._init._disconnect_mcp_tools", new=AsyncMock()))
            stack.enter_context(
                patch("agno.team._run._reclaim_own_requirements", side_effect=lambda _t, reqs, _rid: reqs)
            )
            stack.enter_context(
                patch(
                    "agno.team._run._group_requirements_for_continue",
                    return_value=[(member, member_run_output, [requirement])],
                )
            )
            stack.enter_context(patch("agno.team._tools._check_and_refresh_mcp_tools", new=AsyncMock()))
            stack.enter_context(patch("agno.team._tools._aget_learning_tools", new=AsyncMock(return_value=[])))
            stack.enter_context(patch("agno.team._tools._determine_tools_for_model", return_value=[]))
            stack.enter_context(patch("agno.team._run._get_continue_run_messages", return_value=MagicMock(messages=[])))
            yield

    def test_sync_respond_directly_returns_member_cancellation_without_leader(self):
        from agno.team._run import continue_run_dispatch

        team, session, run_response, requirement, member, member_run_output, _ = self._make_case()
        team.retries = 1

        with (
            self._sync_dispatch_patches(session, member, member_run_output, requirement, self._sync_opts()),
            patch("agno.team._run.register_run"),
            patch("agno.team._run.cleanup_run"),
            patch("agno.team._init._disconnect_connectable_tools"),
            patch("agno.team._run.handle_event"),
            patch("agno.team._run.call_model_with_fallback") as leader_model,
            patch(
                "agno.team._run._cleanup_and_store",
                side_effect=[RuntimeError("transient storage failure"), None],
            ) as cleanup,
            patch("agno.team._telemetry.log_team_telemetry"),
        ):
            result = continue_run_dispatch(team, run_response=run_response, stream=False)

        assert result is run_response
        assert result.status == RunStatus.completed
        assert result.content == self.cancellation
        assert self.cancellation in str(result.tools[0].result)
        member.continue_run.assert_called_once()
        leader_model.assert_not_called()
        assert cleanup.call_count == 2

    @pytest.mark.parametrize("content", [False, 0, "", [], {}])
    def test_records_falsey_direct_member_content_exactly(self, content):
        from agno.team._run import _record_member_continuation_result

        team, _, run_response, _, _, _, member_response = self._make_case()
        member_response.content = content
        member_response.content_type = "application/json"

        recorded = _record_member_continuation_result(team, run_response, member_response)

        assert recorded == content
        assert run_response.content == content
        assert run_response.content_type == "application/json"

    def test_sync_coordinate_mode_still_runs_leader_after_member_continue(self):
        from agno.team._run import continue_run_dispatch

        team, session, run_response, requirement, member, member_run_output, _ = self._make_case(respond_directly=False)
        leader_result = object()

        with (
            self._sync_dispatch_patches(session, member, member_run_output, requirement, self._sync_opts()),
            patch("agno.team._run._prepare_member_hitl_continuation"),
            patch("agno.team._run._continue_run", return_value=leader_result) as leader_continue,
        ):
            result = continue_run_dispatch(team, run_response=run_response, stream=False)

        assert result is leader_result
        member.continue_run.assert_called_once()
        leader_continue.assert_called_once()

    def test_sync_direct_stream_forwards_member_content_without_stream_events(self):
        from agno.run.agent import RunContentEvent, RunOutput
        from agno.team._run import _route_requirements_to_members_stream

        team, session, run_response, requirement, member, member_run_output, _ = self._make_case()
        content_event = RunContentEvent(
            run_id="member-run-1",
            session_id="session-1",
            content=self.cancellation,
        )
        member_final = RunOutput(
            run_id="member-run-1",
            session_id="session-1",
            status=RunStatus.completed,
            content=self.cancellation,
        )
        member.continue_run = MagicMock(return_value=iter([content_event, member_final]))
        member_results = []

        with (
            patch(
                "agno.team._run._group_requirements_for_continue",
                return_value=[(member, member_run_output, [requirement])],
            ),
            patch("agno.team._run.register_member_run"),
        ):
            events = list(
                _route_requirements_to_members_stream(
                    team,
                    run_response=run_response,
                    session=session,
                    member_results=member_results,
                    stream_events=False,
                )
            )

        assert events == [content_event]
        assert member_results == [f"[Member 1]: {self.cancellation}"]

    def test_sync_stream_respond_directly_emits_team_terminal_without_leader(self):
        from agno.run.agent import RunOutput
        from agno.run.team import RunCompletedEvent, RunContentCompletedEvent, RunContinuedEvent
        from agno.team._run import continue_run_dispatch

        team, session, run_response, requirement, member, member_run_output, _ = self._make_case()
        member_final = RunOutput(
            run_id="member-run-1",
            session_id="session-1",
            status=RunStatus.completed,
            content=self.cancellation,
        )
        member.continue_run = MagicMock(return_value=iter([member_final]))
        team.retries = 1

        with (
            self._sync_dispatch_patches(
                session,
                member,
                member_run_output,
                requirement,
                self._sync_opts(stream=True, stream_events=True, yield_run_output=True),
            ),
            patch("agno.team._run.register_run"),
            patch("agno.team._run.cleanup_run"),
            patch("agno.team._init._disconnect_connectable_tools"),
            patch("agno.team._run._handle_team_tool_call_updates_stream") as team_tool_updates,
            patch("agno.team._response._handle_model_response_stream") as leader_stream,
            patch("agno.team._response.parse_response_with_parser_model_stream") as parser_stream,
            patch(
                "agno.team._run._cleanup_and_store",
                side_effect=[RuntimeError("transient storage failure"), None],
            ) as cleanup,
            patch("agno.team._telemetry.log_team_telemetry"),
        ):
            events = list(
                continue_run_dispatch(
                    team,
                    run_response=run_response,
                    stream=True,
                    stream_events=True,
                    yield_run_output=True,
                )
            )

        assert any(isinstance(event, RunContentCompletedEvent) for event in events)
        assert any(isinstance(event, RunContinuedEvent) for event in events)
        assert any(isinstance(event, RunCompletedEvent) for event in events)
        assert events[-1] is run_response
        assert run_response.status == RunStatus.completed
        assert run_response.content == self.cancellation
        member.continue_run.assert_called_once()
        team_tool_updates.assert_not_called()
        leader_stream.assert_not_called()
        parser_stream.assert_not_called()
        assert cleanup.call_count == 2

    @pytest.mark.parametrize("respond_directly", [True, False])
    def test_async_member_continuation_respects_response_mode(self, respond_directly):
        from agno.team._run import _acontinue_run

        team, session, run_response, requirement, member, member_run_output, _ = self._make_case(
            respond_directly=respond_directly
        )
        run_context = MagicMock()

        async def _exercise():
            with (
                self._async_dispatch_patches(session, member, member_run_output, requirement),
                patch("agno.team._run.handle_event"),
                patch(
                    "agno.team._run._ahandle_model_response_for_continue",
                    new=AsyncMock(return_value=None),
                ) as leader_continue,
                patch("agno.team._run._acleanup_and_store", new=AsyncMock()) as cleanup,
                patch("agno.team._telemetry.alog_team_telemetry", new=AsyncMock()),
            ):
                if respond_directly:
                    team.retries = 1
                    cleanup.side_effect = [RuntimeError("transient storage failure"), None]
                result = await _acontinue_run(
                    team,
                    session_id="session-1",
                    run_context=run_context,
                    run_response=run_response,
                )

            assert result is run_response
            assert result.status == RunStatus.completed
            member.acontinue_run.assert_awaited_once()
            if respond_directly:
                assert result.content == self.cancellation
                assert self.cancellation in str(result.tools[0].result)
                leader_continue.assert_not_awaited()
            else:
                leader_continue.assert_awaited_once()
            assert cleanup.await_count == (2 if respond_directly else 1)

        asyncio.run(_exercise())

    def test_async_stream_respond_directly_emits_team_terminal_without_leader(self):
        from agno.run.agent import RunOutput
        from agno.run.team import RunCompletedEvent, RunContentCompletedEvent, RunContinuedEvent
        from agno.team._run import _acontinue_run_stream

        team, session, run_response, requirement, member, member_run_output, _ = self._make_case()
        run_context = MagicMock()
        member_final = RunOutput(
            run_id="member-run-1",
            session_id="session-1",
            status=RunStatus.completed,
            content=self.cancellation,
        )

        async def _member_stream(*args, **kwargs):
            yield member_final

        async def _empty_stream(*args, **kwargs):
            if False:
                yield None

        member.acontinue_run = MagicMock(side_effect=_member_stream)
        leader_stream = MagicMock(side_effect=_empty_stream)
        team.retries = 1

        async def _exercise():
            with (
                self._async_dispatch_patches(session, member, member_run_output, requirement),
                patch("agno.team._response._ahandle_model_response_stream", new=leader_stream),
                patch("agno.team._response.aparse_response_with_parser_model_stream", new=_empty_stream),
                patch(
                    "agno.team._run._acleanup_and_store",
                    new=AsyncMock(side_effect=[RuntimeError("transient storage failure"), None]),
                ) as cleanup,
                patch("agno.team._telemetry.alog_team_telemetry", new=AsyncMock()),
            ):
                events = []
                async for event in _acontinue_run_stream(
                    team,
                    session_id="session-1",
                    run_context=run_context,
                    run_response=run_response,
                    stream_events=True,
                    yield_run_output=True,
                ):
                    events.append(event)

            assert any(isinstance(event, RunContentCompletedEvent) for event in events)
            assert any(isinstance(event, RunContinuedEvent) for event in events)
            assert any(isinstance(event, RunCompletedEvent) for event in events)
            assert events[-1] is run_response
            assert run_response.status == RunStatus.completed
            assert run_response.content == self.cancellation
            member.acontinue_run.assert_called_once()
            leader_stream.assert_not_called()
            assert cleanup.await_count == 2

        asyncio.run(_exercise())

    def test_async_direct_cancellation_after_member_resume_stays_cancelled(self):
        from agno.exceptions import RunCancelledException
        from agno.team._run import _acontinue_run

        team, session, run_response, requirement, member, member_run_output, _ = self._make_case()
        run_context = MagicMock()

        async def _exercise():
            cancellation_check = AsyncMock(side_effect=RunCancelledException("cancelled during member resume"))
            with (
                self._async_dispatch_patches(session, member, member_run_output, requirement),
                patch("agno.team._run.araise_if_cancelled", new=cancellation_check),
                patch(
                    "agno.team._run._ahandle_model_response_for_continue",
                    new=AsyncMock(return_value=None),
                ) as leader_continue,
                patch("agno.team._run.adrain_member_tasks", new=AsyncMock()),
                patch("agno.team._run._acleanup_and_store", new=AsyncMock()),
            ):
                result = await _acontinue_run(
                    team,
                    session_id="session-1",
                    run_context=run_context,
                    run_response=run_response,
                )

            cancellation_check.assert_awaited_once_with("team-run-1")
            assert result.status == RunStatus.cancelled
            leader_continue.assert_not_awaited()

        asyncio.run(_exercise())

    def test_async_stream_direct_cancellation_after_member_resume_stays_cancelled(self):
        from agno.exceptions import RunCancelledException
        from agno.run.agent import RunOutput
        from agno.run.team import RunCancelledEvent
        from agno.team._run import _acontinue_run_stream

        team, session, run_response, requirement, member, member_run_output, _ = self._make_case()
        run_context = MagicMock()
        member_final = RunOutput(
            run_id="member-run-1",
            session_id="session-1",
            status=RunStatus.cancelled,
            content="cancelled during member resume",
        )

        async def _member_stream(*args, **kwargs):
            yield member_final

        member.acontinue_run = MagicMock(side_effect=_member_stream)

        async def _exercise():
            cancellation_check = AsyncMock(side_effect=RunCancelledException("cancelled during member resume"))
            with (
                self._async_dispatch_patches(session, member, member_run_output, requirement),
                patch("agno.team._run.araise_if_cancelled", new=cancellation_check),
                patch("agno.team._run.adrain_member_tasks", new=AsyncMock()),
                patch("agno.team._run._acleanup_and_store", new=AsyncMock()),
            ):
                events = []
                async for event in _acontinue_run_stream(
                    team,
                    session_id="session-1",
                    run_context=run_context,
                    run_response=run_response,
                    stream_events=True,
                    yield_run_output=True,
                ):
                    events.append(event)

            cancellation_check.assert_awaited_once_with("team-run-1")
            assert any(isinstance(event, RunCancelledEvent) for event in events)
            assert events[-1] is run_response
            assert run_response.status == RunStatus.cancelled

        asyncio.run(_exercise())

    def test_async_direct_stream_forwards_member_content_without_stream_events(self):
        from agno.run.agent import RunContentEvent, RunOutput
        from agno.team._run import _aroute_requirements_to_members_stream

        team, session, run_response, requirement, member, member_run_output, _ = self._make_case()
        content_event = RunContentEvent(
            run_id="member-run-1",
            session_id="session-1",
            content=self.cancellation,
        )
        member_final = RunOutput(
            run_id="member-run-1",
            session_id="session-1",
            status=RunStatus.completed,
            content=self.cancellation,
        )

        async def _member_stream(*args, **kwargs):
            yield content_event
            yield member_final

        member.acontinue_run = MagicMock(side_effect=_member_stream)
        member_results = []

        async def _exercise():
            with (
                patch(
                    "agno.team._run._group_requirements_for_continue",
                    return_value=[(member, member_run_output, [requirement])],
                ),
                patch("agno.team._run.aregister_member_run", new=AsyncMock()),
            ):
                events = []
                async for event in _aroute_requirements_to_members_stream(
                    team,
                    run_response=run_response,
                    session=session,
                    member_results=member_results,
                    stream_events=False,
                ):
                    events.append(event)

            assert events == [content_event]
            assert member_results == [f"[Member 1]: {self.cancellation}"]

        asyncio.run(_exercise())


# ===========================================================================
# 17. Forwarding team run_context state to member.continue_run
# ===========================================================================


class TestMemberContinueKwargsFromRunContext:
    """Verify the helper that builds kwargs forwarded to member continue_run calls."""

    def test_none_run_context_returns_empty(self):
        from agno.team._run import _member_continue_kwargs_from_run_context

        assert _member_continue_kwargs_from_run_context(None) == {}

    def test_forwards_dependencies_metadata_filters(self):
        from agno.run import RunContext
        from agno.team._run import _member_continue_kwargs_from_run_context

        rc = RunContext(
            run_id="r",
            session_id="s",
            user_id="u",
            session_state={"unused": True},
            dependencies={"user_token": "Bearer xyz"},
            metadata={"trace": 1},
            knowledge_filters={"tag": "v"},
        )

        kwargs = _member_continue_kwargs_from_run_context(rc)
        assert kwargs["dependencies"] == {"user_token": "Bearer xyz"}
        assert kwargs["metadata"] == {"trace": 1}
        assert kwargs["knowledge_filters"] == {"tag": "v"}
        # Agent.acontinue_run does not accept session_state — must not be forwarded
        # or it would be silently swallowed by **kwargs and confuse callers.
        assert "session_state" not in kwargs

    def test_only_forwards_set_fields(self):
        from agno.run import RunContext
        from agno.team._run import _member_continue_kwargs_from_run_context

        rc = RunContext(
            run_id="r",
            session_id="s",
            user_id="u",
            session_state=None,
            dependencies=None,
            metadata=None,
            knowledge_filters=None,
        )
        assert _member_continue_kwargs_from_run_context(rc) == {}


class TestRoutingForwardsRunContextToMembers:
    """Routing functions must forward team dependencies to member.continue_run.

    Forward team run_context state to member.continue_run.
    """

    def _make_run_response_with_member_req(self):
        run_response = MagicMock()
        run_response.run_id = "team-run-1"
        run_response.member_responses = []

        member_run_output = MagicMock()
        member_run_output.run_id = "member-run-1"
        member_run_output.tools = None
        member_run_output.is_paused = False
        member_run_output.content = "done"

        req = _make_requirement(requires_confirmation=True)
        req.member_agent_id = "member-id-1"
        req.member_run_id = "member-run-1"
        req._member_run_response = member_run_output

        run_response.requirements = [req]

        session = MagicMock()
        session.session_id = "session-1"

        return run_response, session, member_run_output

    def _make_run_context(self):
        from agno.run import RunContext

        return RunContext(
            run_id="team-run-1",
            session_id="session-1",
            user_id="user-1",
            session_state={"local": "state"},
            dependencies={"user_token": "Bearer abc"},
            metadata={"trace": "id"},
            knowledge_filters={"tag": "v"},
        )

    def test_sync_routing_forwards_dependencies(self):
        from agno.team._run import _route_requirements_to_members

        run_response, session, _member_run_output = self._make_run_response_with_member_req()
        run_context = self._make_run_context()

        member = MagicMock()
        member.name = "Member 1"
        member_response = MagicMock(is_paused=False, content="ok")
        member.continue_run = MagicMock(return_value=member_response)

        team = MagicMock()

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            _route_requirements_to_members(team, run_response=run_response, session=session, run_context=run_context)

        member.continue_run.assert_called_once()
        kwargs = member.continue_run.call_args.kwargs
        assert kwargs["dependencies"] == {"user_token": "Bearer abc"}
        assert kwargs["metadata"] == {"trace": "id"}
        assert kwargs["knowledge_filters"] == {"tag": "v"}

    def test_sync_routing_run_id_fallback_forwards_dependencies(self):
        from agno.team._run import _route_requirements_to_members

        run_response, session, _ = self._make_run_response_with_member_req()
        # Force the run_id fallback path (no cached member RunOutput)
        run_response.requirements[0]._member_run_response = None
        run_response.member_responses = []
        run_context = self._make_run_context()

        member = MagicMock()
        member.name = "Member 1"
        member.continue_run = MagicMock(return_value=MagicMock(is_paused=False, content="ok"))

        team = MagicMock()

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            _route_requirements_to_members(team, run_response=run_response, session=session, run_context=run_context)

        kwargs = member.continue_run.call_args.kwargs
        assert kwargs["dependencies"] == {"user_token": "Bearer abc"}

    def test_async_routing_forwards_dependencies(self):
        from agno.team._run import _aroute_requirements_to_members

        run_response, session, _ = self._make_run_response_with_member_req()
        run_context = self._make_run_context()

        member = MagicMock()
        member.name = "Member 1"
        member_response = MagicMock(is_paused=False, content="ok")
        member.acontinue_run = AsyncMock(return_value=member_response)

        team = MagicMock()

        async def _exercise():
            with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
                await _aroute_requirements_to_members(
                    team, run_response=run_response, session=session, run_context=run_context
                )

        asyncio.run(_exercise())

        member.acontinue_run.assert_awaited_once()
        kwargs = member.acontinue_run.call_args.kwargs
        assert kwargs["dependencies"] == {"user_token": "Bearer abc"}
        assert kwargs["metadata"] == {"trace": "id"}
        assert kwargs["knowledge_filters"] == {"tag": "v"}

    def test_async_streaming_routing_forwards_dependencies(self):
        from agno.team._run import _aroute_requirements_to_members_stream

        run_response, session, _ = self._make_run_response_with_member_req()
        run_context = self._make_run_context()

        member_response = MagicMock(is_paused=False, content="ok")

        async def _member_stream(*args, **kwargs):
            yield member_response

        member = MagicMock()
        member.name = "Member 1"
        member.acontinue_run = MagicMock(side_effect=lambda *a, **kw: _member_stream())

        team = MagicMock()
        team.stream_member_events = False
        team.events_to_skip = []
        team.store_events = False

        async def _exercise():
            with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
                member_results = []
                async for _ in _aroute_requirements_to_members_stream(
                    team,
                    run_response=run_response,
                    session=session,
                    member_results=member_results,
                    run_context=run_context,
                    stream_events=False,
                ):
                    pass

        asyncio.run(_exercise())

        member.acontinue_run.assert_called_once()
        kwargs = member.acontinue_run.call_args.kwargs
        assert kwargs["dependencies"] == {"user_token": "Bearer abc"}
        assert kwargs["metadata"] == {"trace": "id"}
        assert kwargs["knowledge_filters"] == {"tag": "v"}

    def test_sync_streaming_routing_forwards_dependencies(self):
        from agno.team._run import _route_requirements_to_members_stream

        run_response, session, _ = self._make_run_response_with_member_req()
        run_context = self._make_run_context()

        member_response = MagicMock(is_paused=False, content="ok")

        def _member_stream(*args, **kwargs):
            yield member_response

        member = MagicMock()
        member.name = "Member 1"
        member.continue_run = MagicMock(side_effect=lambda *a, **kw: _member_stream())

        team = MagicMock()
        team.stream_member_events = False
        team.events_to_skip = []
        team.store_events = False

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            member_results = []
            list(
                _route_requirements_to_members_stream(
                    team,
                    run_response=run_response,
                    session=session,
                    member_results=member_results,
                    run_context=run_context,
                    stream_events=False,
                )
            )

        member.continue_run.assert_called_once()
        kwargs = member.continue_run.call_args.kwargs
        assert kwargs["dependencies"] == {"user_token": "Bearer abc"}
        assert kwargs["metadata"] == {"trace": "id"}
        assert kwargs["knowledge_filters"] == {"tag": "v"}

    def test_routing_with_none_run_context_does_not_inject_kwargs(self):
        """When the team has no run_context (defensive), no forwarding kwargs are added."""
        from agno.team._run import _route_requirements_to_members

        run_response, session, _ = self._make_run_response_with_member_req()

        member = MagicMock()
        member.name = "Member 1"
        member.continue_run = MagicMock(return_value=MagicMock(is_paused=False, content="ok"))

        team = MagicMock()

        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            _route_requirements_to_members(team, run_response=run_response, session=session, run_context=None)

        kwargs = member.continue_run.call_args.kwargs
        assert "dependencies" not in kwargs
        assert "metadata" not in kwargs
        assert "knowledge_filters" not in kwargs
