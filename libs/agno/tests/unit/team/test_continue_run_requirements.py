"""Tests for Team continue_run helpers (propagation, routing, normalization)."""

from unittest.mock import MagicMock, patch

from agno.models.response import ToolExecution
from agno.run.requirement import RunRequirement

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
