"""Tests for _get_team_paused_content and external_execution_silent behavior."""

from agno.models.response import ToolExecution
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.team._hooks import _get_team_paused_content


def _make_requirement(
    tool_name: str,
    external_execution: bool = False,
    external_execution_silent: bool = False,
    requires_confirmation: bool = False,
    requires_user_input: bool = False,
    member_agent_name: str | None = None,
) -> RunRequirement:
    """Helper to create a RunRequirement with specific flags."""
    tool_execution = ToolExecution(
        tool_call_id="test_call_id",
        tool_name=tool_name,
        tool_args={},
        external_execution_required=external_execution,
        external_execution_silent=external_execution_silent if external_execution else None,
        requires_confirmation=requires_confirmation,
        requires_user_input=requires_user_input,
    )
    req = RunRequirement(tool_execution=tool_execution)
    req.member_agent_name = member_agent_name
    return req


def _make_team_run_output(requirements: list[RunRequirement]) -> TeamRunOutput:
    """Helper to create TeamRunOutput with requirements."""
    return TeamRunOutput(requirements=requirements)


class TestGetTeamPausedContent:
    """Tests for _get_team_paused_content function."""

    def test_no_requirements_returns_default(self):
        run_response = _make_team_run_output([])
        assert _get_team_paused_content(run_response) == "Team run paused."

    def test_all_resolved_returns_default(self):
        req = _make_requirement("my_tool", external_execution=True)
        req.set_external_execution_result("done")  # Resolve it
        run_response = _make_team_run_output([req])
        assert _get_team_paused_content(run_response) == "Team run paused."

    def test_external_execution_shown(self):
        req = _make_requirement(
            "send_email",
            external_execution=True,
            member_agent_name="EmailAgent",
        )
        run_response = _make_team_run_output([req])
        content = _get_team_paused_content(run_response)
        assert "EmailAgent: send_email requires external execution" in content

    def test_confirmation_shown(self):
        req = _make_requirement(
            "delete_file",
            requires_confirmation=True,
            member_agent_name="FileAgent",
        )
        run_response = _make_team_run_output([req])
        content = _get_team_paused_content(run_response)
        assert "FileAgent: delete_file requires confirmation" in content

    def test_user_input_shown(self):
        req = _make_requirement(
            "get_credentials",
            requires_user_input=True,
            member_agent_name="AuthAgent",
        )
        run_response = _make_team_run_output([req])
        content = _get_team_paused_content(run_response)
        assert "AuthAgent: get_credentials requires user input" in content


class TestExternalExecutionSilent:
    """Tests for external_execution_silent filtering in Team paused content."""

    def test_silent_requirement_skipped(self):
        """Silent external execution should not appear in paused content."""
        req = _make_requirement(
            "change_theme",
            external_execution=True,
            external_execution_silent=True,
            member_agent_name="UIAgent",
        )
        run_response = _make_team_run_output([req])
        content = _get_team_paused_content(run_response)
        # Silent requirement: should return empty string
        assert content == ""

    def test_non_silent_requirement_shown(self):
        """Non-silent external execution should appear in paused content."""
        req = _make_requirement(
            "send_email",
            external_execution=True,
            external_execution_silent=False,
            member_agent_name="EmailAgent",
        )
        run_response = _make_team_run_output([req])
        content = _get_team_paused_content(run_response)
        assert "EmailAgent: send_email requires external execution" in content

    def test_mixed_silent_and_non_silent(self):
        """Mixed requirements: only non-silent should appear."""
        silent_req = _make_requirement(
            "change_theme",
            external_execution=True,
            external_execution_silent=True,
            member_agent_name="UIAgent",
        )
        non_silent_req = _make_requirement(
            "send_email",
            external_execution=True,
            external_execution_silent=False,
            member_agent_name="EmailAgent",
        )
        run_response = _make_team_run_output([silent_req, non_silent_req])
        content = _get_team_paused_content(run_response)
        # Non-silent should be shown
        assert "EmailAgent: send_email requires external execution" in content
        # Silent should NOT be shown
        assert "UIAgent" not in content
        assert "change_theme" not in content

    def test_all_silent_returns_empty(self):
        """When all requirements are silent, return empty string."""
        req1 = _make_requirement(
            "change_theme",
            external_execution=True,
            external_execution_silent=True,
            member_agent_name="UIAgent",
        )
        req2 = _make_requirement(
            "update_ui",
            external_execution=True,
            external_execution_silent=True,
            member_agent_name="UIAgent",
        )
        run_response = _make_team_run_output([req1, req2])
        content = _get_team_paused_content(run_response)
        assert content == ""

    def test_silent_with_confirmation_mixed(self):
        """Silent external + non-silent confirmation: only confirmation shown."""
        silent_req = _make_requirement(
            "change_theme",
            external_execution=True,
            external_execution_silent=True,
            member_agent_name="UIAgent",
        )
        confirm_req = _make_requirement(
            "delete_file",
            requires_confirmation=True,
            member_agent_name="FileAgent",
        )
        run_response = _make_team_run_output([silent_req, confirm_req])
        content = _get_team_paused_content(run_response)
        # Confirmation should be shown
        assert "FileAgent: delete_file requires confirmation" in content
        # Silent external should NOT be shown
        assert "UIAgent" not in content


class TestRunRequirementExternalExecutionSilentProperty:
    """Tests for RunRequirement.external_execution_silent property."""

    def test_silent_property_true(self):
        req = _make_requirement(
            "my_tool",
            external_execution=True,
            external_execution_silent=True,
        )
        assert req.external_execution_silent is True

    def test_silent_property_false_when_not_external(self):
        """Silent property requires needs_external_execution to be True."""
        req = _make_requirement(
            "my_tool",
            external_execution=False,
            external_execution_silent=True,  # Flag set but not external execution
        )
        # Should be False because needs_external_execution is False
        assert req.external_execution_silent is False

    def test_silent_property_false_when_not_silent(self):
        req = _make_requirement(
            "my_tool",
            external_execution=True,
            external_execution_silent=False,
        )
        assert req.external_execution_silent is False

    def test_silent_property_false_when_resolved(self):
        """Once resolved, external_execution_silent should be False."""
        req = _make_requirement(
            "my_tool",
            external_execution=True,
            external_execution_silent=True,
        )
        assert req.external_execution_silent is True
        req.set_external_execution_result("done")
        # After resolution, needs_external_execution is False
        assert req.external_execution_silent is False
