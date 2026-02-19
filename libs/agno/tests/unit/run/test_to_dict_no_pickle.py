"""Tests for to_dict() methods that avoid deep-copy/pickle issues.

These tests verify that to_dict() methods on session and run dataclasses
work correctly when fields contain non-picklable objects such as module
references. This is a regression test for issue #6115 where
AsyncPostgresDb.upsert_session failed with "cannot pickle 'module' object".
"""

import types

from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession


class TestSessionToDictNonPicklable:
    """Test that session to_dict() works with non-picklable objects in fields."""

    def test_agent_session_to_dict_with_module_in_session_data(self):
        """AgentSession.to_dict() should not fail when session_data contains a module."""
        session = AgentSession(
            session_id="test-session-1",
            agent_id="agent-1",
            session_data={"module_ref": types},  # non-picklable module reference
        )
        result = session.to_dict()
        assert result["session_id"] == "test-session-1"
        assert result["agent_id"] == "agent-1"
        assert result["session_data"]["module_ref"] is types

    def test_agent_session_to_dict_with_module_in_metadata(self):
        """AgentSession.to_dict() should not fail when metadata contains a module."""
        session = AgentSession(
            session_id="test-session-2",
            agent_id="agent-2",
            metadata={"some_module": types},
        )
        result = session.to_dict()
        assert result["session_id"] == "test-session-2"
        assert result["metadata"]["some_module"] is types

    def test_team_session_to_dict_with_module_in_session_data(self):
        """TeamSession.to_dict() should not fail when session_data contains a module."""
        session = TeamSession(
            session_id="test-session-3",
            team_id="team-1",
            session_data={"module_ref": types},
        )
        result = session.to_dict()
        assert result["session_id"] == "test-session-3"
        assert result["team_id"] == "team-1"
        assert result["session_data"]["module_ref"] is types

    def test_agent_session_to_dict_preserves_all_fields(self):
        """AgentSession.to_dict() should preserve all non-None fields."""
        session = AgentSession(
            session_id="test-session-4",
            agent_id="agent-4",
            user_id="user-4",
            team_id="team-4",
            workflow_id="workflow-4",
            session_data={"key": "value"},
            metadata={"meta_key": "meta_value"},
            agent_data={"agent_key": "agent_value"},
            created_at=1000,
            updated_at=2000,
        )
        result = session.to_dict()
        assert result["session_id"] == "test-session-4"
        assert result["agent_id"] == "agent-4"
        assert result["user_id"] == "user-4"
        assert result["team_id"] == "team-4"
        assert result["workflow_id"] == "workflow-4"
        assert result["session_data"] == {"key": "value"}
        assert result["metadata"] == {"meta_key": "meta_value"}
        assert result["agent_data"] == {"agent_key": "agent_value"}
        assert result["created_at"] == 1000
        assert result["updated_at"] == 2000
        assert result["runs"] is None
        assert result["summary"] is None

    def test_team_session_to_dict_preserves_all_fields(self):
        """TeamSession.to_dict() should preserve all non-None fields."""
        session = TeamSession(
            session_id="test-session-5",
            team_id="team-5",
            user_id="user-5",
            workflow_id="workflow-5",
            team_data={"team_key": "team_value"},
            session_data={"key": "value"},
            metadata={"meta_key": "meta_value"},
            created_at=1000,
            updated_at=2000,
        )
        result = session.to_dict()
        assert result["session_id"] == "test-session-5"
        assert result["team_id"] == "team-5"
        assert result["user_id"] == "user-5"
        assert result["workflow_id"] == "workflow-5"
        assert result["team_data"] == {"team_key": "team_value"}
        assert result["session_data"] == {"key": "value"}
        assert result["metadata"] == {"meta_key": "meta_value"}
        assert result["created_at"] == 1000
        assert result["updated_at"] == 2000
        assert result["runs"] is None
        assert result["summary"] is None


class TestRunOutputToDictNonPicklable:
    """Test that RunOutput to_dict() works with non-picklable objects."""

    def test_run_output_to_dict_with_module_in_session_state(self):
        """RunOutput.to_dict() should not fail when session_state contains a module."""
        run = RunOutput(
            run_id="run-1",
            agent_id="agent-1",
            session_state={"module_ref": types},  # non-picklable module reference
        )
        result = run.to_dict()
        assert result["run_id"] == "run-1"
        assert result["agent_id"] == "agent-1"
        assert result["session_state"]["module_ref"] is types

    def test_run_output_to_dict_with_module_in_model_provider_data(self):
        """RunOutput.to_dict() should not fail when model_provider_data contains a module."""
        run = RunOutput(
            run_id="run-2",
            agent_id="agent-2",
            model_provider_data={"module_ref": types},
        )
        result = run.to_dict()
        assert result["run_id"] == "run-2"
        assert result["model_provider_data"]["module_ref"] is types

    def test_run_output_to_dict_preserves_basic_fields(self):
        """RunOutput.to_dict() should correctly include non-None basic fields."""
        run = RunOutput(
            run_id="run-3",
            agent_id="agent-3",
            agent_name="TestAgent",
            session_id="session-3",
            content="Hello world",
            model="gpt-5",
        )
        result = run.to_dict()
        assert result["run_id"] == "run-3"
        assert result["agent_id"] == "agent-3"
        assert result["agent_name"] == "TestAgent"
        assert result["session_id"] == "session-3"
        assert result["content"] == "Hello world"
        assert result["model"] == "gpt-5"

    def test_run_output_to_dict_excludes_none_fields(self):
        """RunOutput.to_dict() should exclude fields with None values."""
        run = RunOutput(
            run_id="run-4",
            agent_id="agent-4",
        )
        result = run.to_dict()
        assert result["run_id"] == "run-4"
        assert "workflow_id" not in result  # None fields excluded
        assert "user_id" not in result


class TestTeamRunOutputToDictNonPicklable:
    """Test that TeamRunOutput to_dict() works with non-picklable objects."""

    def test_team_run_output_to_dict_with_module_in_session_state(self):
        """TeamRunOutput.to_dict() should not fail when session_state contains a module."""
        run = TeamRunOutput(
            run_id="run-team-1",
            team_id="team-1",
            session_state={"module_ref": types},
        )
        result = run.to_dict()
        assert result["run_id"] == "run-team-1"
        assert result["team_id"] == "team-1"
        assert result["session_state"]["module_ref"] is types


class TestToolExecutionToDictNonPicklable:
    """Test that ToolExecution to_dict() works with non-picklable objects."""

    def test_tool_execution_to_dict_with_module_in_tool_args(self):
        """ToolExecution.to_dict() should not fail when tool_args contains a module."""
        tool = ToolExecution(
            tool_call_id="call-1",
            tool_name="test_tool",
            tool_args={"module_ref": types},
        )
        result = tool.to_dict()
        assert result["tool_call_id"] == "call-1"
        assert result["tool_name"] == "test_tool"
        assert result["tool_args"]["module_ref"] is types


class TestEndToEndSessionUpsertSerialization:
    """End-to-end test simulating the AsyncPostgresDb upsert_session flow."""

    def test_agent_session_with_run_containing_module_ref(self):
        """Simulate the full path: AgentSession with RunOutput containing module ref."""
        run = RunOutput(
            run_id="run-e2e-1",
            agent_id="agent-e2e-1",
            session_state={"imported_module": types},
            content="Test response",
        )
        session = AgentSession(
            session_id="session-e2e-1",
            agent_id="agent-e2e-1",
            runs=[run],
            session_data={"session_state": {"imported_module": types}},
        )
        # This is what AsyncPostgresDb.upsert_session calls
        session_dict = session.to_dict()

        assert session_dict["session_id"] == "session-e2e-1"
        assert session_dict["agent_id"] == "agent-e2e-1"
        assert len(session_dict["runs"]) == 1
        assert session_dict["runs"][0]["run_id"] == "run-e2e-1"
        assert session_dict["session_data"]["session_state"]["imported_module"] is types

    def test_team_session_with_run_containing_module_ref(self):
        """Simulate the full path: TeamSession with TeamRunOutput containing module ref."""
        run = TeamRunOutput(
            run_id="run-e2e-2",
            team_id="team-e2e-2",
            session_state={"imported_module": types},
            content="Test response",
        )
        session = TeamSession(
            session_id="session-e2e-2",
            team_id="team-e2e-2",
            runs=[run],
            session_data={"session_state": {"imported_module": types}},
        )
        session_dict = session.to_dict()

        assert session_dict["session_id"] == "session-e2e-2"
        assert session_dict["team_id"] == "team-e2e-2"
        assert len(session_dict["runs"]) == 1
        assert session_dict["runs"][0]["run_id"] == "run-e2e-2"

    def test_workflow_session_with_module_ref_in_data(self):
        """WorkflowSession.to_dict() already works without asdict(), confirm it still does."""
        session = WorkflowSession(
            session_id="session-e2e-3",
            workflow_id="workflow-e2e-3",
            session_data={"session_state": {"imported_module": types}},
        )
        session_dict = session.to_dict()

        assert session_dict["session_id"] == "session-e2e-3"
        assert session_dict["workflow_id"] == "workflow-e2e-3"
        assert session_dict["session_data"]["session_state"]["imported_module"] is types
