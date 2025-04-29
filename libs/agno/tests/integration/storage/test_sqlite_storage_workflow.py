import os

import pytest

from agno.agent import Agent
from agno.run.response import RunResponse
from agno.storage.session.workflow import WorkflowSession
from agno.storage.sqlite import SqliteStorage
from agno.workflow import Workflow


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database file path."""
    db_file = tmp_path / "test_workflow_storage.db"
    yield str(db_file)
    # Clean up the file after tests
    if os.path.exists(db_file):
        os.remove(db_file)


@pytest.fixture
def workflow_storage(temp_db_path):
    """Create a SqliteStorage instance for workflow sessions."""
    storage = SqliteStorage(table_name="workflow_sessions", db_file=temp_db_path, mode="workflow")
    storage.create()
    return storage


class SimpleWorkflow(Workflow):
    """A simple workflow with a single agent for testing."""

    description: str = "A simple workflow for testing storage"

    test_agent: Agent = Agent(
        description="A test agent for the workflow",
    )

    def run(self, query: str) -> RunResponse:
        """Run the workflow with a simple query."""
        response = self.test_agent.run(query)
        return RunResponse(run_id=self.run_id, content=f"Workflow processed: {response.content}")


@pytest.fixture
def workflow_with_storage(workflow_storage):
    """Create a workflow with the test storage."""
    return SimpleWorkflow(storage=workflow_storage, name="TestWorkflow")


def test_storage_creation(temp_db_path):
    """Test that storage is created correctly."""
    storage = SqliteStorage(table_name="workflow_sessions", db_file=temp_db_path, mode="workflow")
    storage.create()
    assert os.path.exists(temp_db_path)
    assert storage.table_exists()


def test_workflow_session_storage(workflow_with_storage, workflow_storage):
    """Test that workflow sessions are properly stored."""
    # Run workflow and get response
    workflow_with_storage.run(query="What is the capital of France?")

    assert workflow_with_storage.storage.mode == "workflow"

    # Get the session ID from the workflow
    session_id = workflow_with_storage.session_id

    # Verify session was stored
    stored_session = workflow_storage.read(session_id)
    assert stored_session is not None
    assert isinstance(stored_session, WorkflowSession)
    assert stored_session.session_id == session_id

    # Verify workflow data was stored
    assert stored_session.workflow_data is not None
    assert stored_session.workflow_data.get("name") == "TestWorkflow"

    # Verify memory contains the run
    assert stored_session.memory is not None
    assert "runs" in stored_session.memory
    assert len(stored_session.memory["runs"]) > 0


def test_multiple_interactions(workflow_with_storage, workflow_storage):
    """Test that multiple interactions are properly stored in the same session."""
    # First interaction
    workflow_with_storage.run(query="What is the capital of France?")

    assert workflow_with_storage.storage.mode == "workflow"
    session_id = workflow_with_storage.session_id

    # Second interaction
    workflow_with_storage.run(query="What is its population?")

    # Verify both interactions are in the same session
    stored_session = workflow_storage.read(session_id)
    assert stored_session is not None
    assert "runs" in stored_session.memory
    runs = stored_session.memory["runs"][session_id]
    assert len(runs) == 2  # Should have 2 runs


def test_session_retrieval_by_user(workflow_storage):
    """Test retrieving sessions filtered by user ID."""
    # Create a session with a specific user ID
    workflow = SimpleWorkflow(storage=workflow_storage, user_id="test_user", name="UserTestWorkflow")
    workflow.run(query="What is the capital of France?")

    assert workflow.storage.mode == "workflow"

    # Get all sessions for the user
    sessions = workflow_storage.get_all_sessions(user_id="test_user")
    assert len(sessions) == 1
    assert sessions[0].user_id == "test_user"

    # Verify no sessions for different user
    other_sessions = workflow_storage.get_all_sessions(user_id="other_user")
    assert len(other_sessions) == 0


def test_session_deletion(workflow_with_storage, workflow_storage):
    """Test deleting a session."""
    # Create a session
    workflow_with_storage.run(query="What is the capital of France?")
    session_id = workflow_with_storage.session_id

    # Verify session exists
    assert workflow_storage.read(session_id) is not None

    # Delete session
    workflow_storage.delete_session(session_id)

    # Verify session was deleted
    assert workflow_storage.read(session_id) is None


def test_get_all_session_ids(workflow_storage):
    """Test retrieving all session IDs."""
    # Create multiple sessions with different user IDs and workflow IDs
    workflow_1 = SimpleWorkflow(storage=workflow_storage, user_id="user1", workflow_id="workflow1", name="Workflow1")
    workflow_2 = SimpleWorkflow(storage=workflow_storage, user_id="user1", workflow_id="workflow2", name="Workflow2")
    workflow_3 = SimpleWorkflow(storage=workflow_storage, user_id="user2", workflow_id="workflow3", name="Workflow3")

    workflow_1.run(query="Question 1")
    workflow_2.run(query="Question 2")
    workflow_3.run(query="Question 3")

    # Get all session IDs
    all_sessions = workflow_storage.get_all_session_ids()
    assert len(all_sessions) == 3

    # Filter by user ID
    user1_sessions = workflow_storage.get_all_session_ids(user_id="user1")
    assert len(user1_sessions) == 2

    # Filter by workflow ID
    workflow1_sessions = workflow_storage.get_all_session_ids(entity_id="workflow1")
    assert len(workflow1_sessions) == 1

    # Filter by both
    filtered_sessions = workflow_storage.get_all_session_ids(user_id="user1", entity_id="workflow2")
    assert len(filtered_sessions) == 1


def test_drop_storage(workflow_storage):
    """Test dropping all sessions from storage."""
    # Create a few sessions
    for i in range(3):
        workflow = SimpleWorkflow(storage=workflow_storage, name=f"Workflow{i}")
        workflow.run(query=f"Question {i}")

    # Verify sessions exist
    assert len(workflow_storage.get_all_session_ids()) == 3

    # Drop all sessions
    workflow_storage.drop()

    # Verify no sessions remain
    assert len(workflow_storage.get_all_session_ids()) == 0


def test_workflow_session_rename(workflow_with_storage, workflow_storage):
    """Test renaming a workflow session."""
    # Create a session
    workflow_with_storage.run(query="What is the capital of France?")
    session_id = workflow_with_storage.session_id

    # Rename the session
    workflow_with_storage.rename_session("My Renamed Session")

    # Verify session was renamed
    stored_session = workflow_storage.read(session_id)
    assert stored_session is not None
    assert stored_session.session_data.get("session_name") == "My Renamed Session"


def test_workflow_rename(workflow_with_storage, workflow_storage):
    """Test renaming a workflow."""
    # Create a session
    workflow_with_storage.run(query="What is the capital of France?")
    session_id = workflow_with_storage.session_id

    # Rename the workflow
    workflow_with_storage.rename("My Renamed Workflow")

    # Verify workflow was renamed
    stored_session = workflow_storage.read(session_id)
    assert stored_session is not None
    assert stored_session.workflow_data.get("name") == "My Renamed Workflow"
