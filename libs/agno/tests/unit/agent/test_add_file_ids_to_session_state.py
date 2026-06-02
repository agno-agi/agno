"""
Unit tests for add_file_ids_to_session_state feature.

When send_media_to_model=False and add_file_ids_to_session_state=True,
uploaded file metadata should be automatically added to session_state.
"""

import pytest

from agno.agent.agent import Agent
from agno.media import File
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.session.agent import AgentSession
from agno.agent._messages import get_run_messages


@pytest.fixture
def run_context():
    """Create a RunContext with an empty session_state."""
    return RunContext(
        run_id="test-run",
        session_id="test-session",
        session_state={},
    )


@pytest.fixture
def run_response():
    """Create a mock RunOutput."""
    return RunOutput(run_id="test-run")


@pytest.fixture
def session():
    """Create a minimal AgentSession."""
    return AgentSession(session_id="test-session")


class TestAddFileIdsToSessionState:
    """Tests for the add_file_ids_to_session_state feature."""

    def test_adds_file_metadata_when_enabled(self, run_context, run_response, session):
        """When add_file_ids_to_session_state=True and send_media_to_model=False,
        file metadata should be added to session_state."""
        agent = Agent(
            id="test-agent",
            name="Test Agent",
            send_media_to_model=False,
            add_file_ids_to_session_state=True,
        )
        files = [
            File(id="file-1", filename="report.pdf", url="https://example.com/report.pdf"),
            File(id="file-2", filename="data.csv"),
        ]

        get_run_messages(
            agent,
            run_response=run_response,
            run_context=run_context,
            session=session,
            input="Analyze these files",
            files=files,
        )

        assert "files" in run_context.session_state
        assert len(run_context.session_state["files"]) == 2
        assert run_context.session_state["files"][0]["file_id"] == "file-1"
        assert run_context.session_state["files"][0]["filename"] == "report.pdf"
        assert run_context.session_state["files"][0]["url"] == "https://example.com/report.pdf"
        assert run_context.session_state["files"][1]["file_id"] == "file-2"
        assert run_context.session_state["files"][1]["filename"] == "data.csv"

    def test_does_not_add_when_disabled(self, run_context, run_response, session):
        """When add_file_ids_to_session_state=False, files should not be added."""
        agent = Agent(
            id="test-agent",
            name="Test Agent",
            send_media_to_model=False,
            add_file_ids_to_session_state=False,
        )
        files = [File(id="file-1", filename="report.pdf")]

        get_run_messages(
            agent,
            run_response=run_response,
            run_context=run_context,
            session=session,
            input="Analyze this file",
            files=files,
        )

        assert "files" not in run_context.session_state

    def test_does_not_add_when_send_media_to_model_true(self, run_context, run_response, session):
        """When send_media_to_model=True, files should not be added to session_state
        (since the model already receives them directly)."""
        agent = Agent(
            id="test-agent",
            name="Test Agent",
            send_media_to_model=True,
            add_file_ids_to_session_state=True,
        )
        files = [File(id="file-1", filename="report.pdf")]

        get_run_messages(
            agent,
            run_response=run_response,
            run_context=run_context,
            session=session,
            input="Analyze this file",
            files=files,
        )

        assert "files" not in run_context.session_state

    def test_does_not_add_when_no_files(self, run_context, run_response, session):
        """When there are no files, nothing should be added."""
        agent = Agent(
            id="test-agent",
            name="Test Agent",
            send_media_to_model=False,
            add_file_ids_to_session_state=True,
        )

        get_run_messages(
            agent,
            run_response=run_response,
            run_context=run_context,
            session=session,
            input="Hello",
            files=None,
        )

        assert "files" not in run_context.session_state

    def test_appends_to_existing_files_in_session_state(self, run_context, run_response, session):
        """File metadata should be appended to existing 'files' key in session_state."""
        run_context.session_state["files"] = [{"file_id": "existing-file", "filename": "old.txt"}]
        agent = Agent(
            id="test-agent",
            name="Test Agent",
            send_media_to_model=False,
            add_file_ids_to_session_state=True,
        )
        files = [File(id="new-file", filename="new.txt")]

        get_run_messages(
            agent,
            run_response=run_response,
            run_context=run_context,
            session=session,
            input="Compare files",
            files=files,
        )

        assert len(run_context.session_state["files"]) == 2
        assert run_context.session_state["files"][0]["file_id"] == "existing-file"
        assert run_context.session_state["files"][1]["file_id"] == "new-file"

    def test_initializes_session_state_when_none(self, run_response, session):
        """When session_state is None, it should be initialized with file metadata."""
        run_context = RunContext(
            run_id="test-run",
            session_id="test-session",
            session_state=None,
        )
        agent = Agent(
            id="test-agent",
            name="Test Agent",
            send_media_to_model=False,
            add_file_ids_to_session_state=True,
        )
        files = [File(id="file-1", filename="report.pdf")]

        get_run_messages(
            agent,
            run_response=run_response,
            run_context=run_context,
            session=session,
            input="Analyze",
            files=files,
        )

        assert run_context.session_state is not None
        assert "files" in run_context.session_state
        assert len(run_context.session_state["files"]) == 1

    def test_default_is_false(self):
        """The default value of add_file_ids_to_session_state should be False."""
        agent = Agent(id="test-agent")
        assert agent.add_file_ids_to_session_state is False

    def test_persists_in_to_dict(self):
        """When True, the setting should appear in to_dict output."""
        agent = Agent(
            id="test-agent",
            send_media_to_model=False,
            add_file_ids_to_session_state=True,
        )
        config = agent.to_dict()
        assert config.get("add_file_ids_to_session_state") is True

    def test_not_in_to_dict_when_false(self):
        """When False (default), the setting should NOT appear in to_dict."""
        agent = Agent(id="test-agent")
        config = agent.to_dict()
        assert "add_file_ids_to_session_state" not in config
