import pytest

from agno.agent import Agent
from agno.run.response import RunResponse
from agno.storage.in_memory import InMemoryStorage
from agno.storage.session.workflow import WorkflowSession
from agno.workflow import Workflow


@pytest.fixture
def workflow_storage():
    """Create an InMemoryStorage instance for workflow sessions."""
    return InMemoryStorage(mode="workflow")


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


def test_storage_creation():
    """Test that storage can be created without errors."""
    storage = InMemoryStorage(mode="workflow")
    assert storage.mode == "workflow"


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
    runs = stored_session.memory["runs"]
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


def test_get_recent_sessions(workflow_storage):
    """Test getting recent sessions."""
    import time

    # Create multiple workflows with different timestamps
    workflows = []
    for i in range(5):
        workflow = SimpleWorkflow(storage=workflow_storage, name=f"Workflow{i}")
        workflow.run(query=f"Question {i}")
        workflows.append(workflow)
        time.sleep(0.01)  # Small delay to ensure different timestamps

    # Test get recent sessions with default limit
    recent_sessions = workflow_storage.get_recent_sessions()
    assert len(recent_sessions) == 2  # Default limit

    # Sessions should be ordered by created_at descending (most recent first)
    session_ids = [s.session_id for s in recent_sessions]
    # The most recent sessions should be from the last workflows created
    assert workflows[-1].session_id in session_ids
    assert workflows[-2].session_id in session_ids

    # Test with custom limit
    recent_sessions = workflow_storage.get_recent_sessions(limit=3)
    assert len(recent_sessions) == 3

    # Test with user_id filter
    # Create a workflow with a specific user_id
    user_workflow = SimpleWorkflow(storage=workflow_storage, user_id="specific_user", name="UserWorkflow")
    user_workflow.run(query="User question")

    recent_sessions = workflow_storage.get_recent_sessions(user_id="specific_user", limit=5)
    assert len(recent_sessions) == 1
    assert recent_sessions[0].user_id == "specific_user"

    # Test with entity_id filter
    entity_workflow = SimpleWorkflow(storage=workflow_storage, workflow_id="specific_workflow", name="EntityWorkflow")
    entity_workflow.run(query="Entity question")

    recent_sessions = workflow_storage.get_recent_sessions(entity_id="specific_workflow", limit=5)
    assert len(recent_sessions) == 1
    assert recent_sessions[0].workflow_id == "specific_workflow"


def test_persistent_memory_across_runs(workflow_storage):
    """Test that memory persists across multiple runs with the same workflow."""
    # Create a workflow with a specific session_id
    workflow = SimpleWorkflow(storage=workflow_storage, session_id="persistent_session", name="PersistentWorkflow")

    # First run
    workflow.run(query="Remember this: my favorite color is blue")

    # Create a new workflow instance with the same session_id
    workflow2 = SimpleWorkflow(storage=workflow_storage, session_id="persistent_session", name="PersistentWorkflow")

    # The second workflow should have access to the previous conversation
    stored_session = workflow_storage.read("persistent_session")
    assert stored_session is not None
    assert len(stored_session.memory["runs"]) > 0

    # Run with the second workflow
    workflow2.run(query="What is my favorite color?")

    # Verify both runs are stored
    final_session = workflow_storage.read("persistent_session")
    assert final_session is not None
    assert len(final_session.memory["runs"]) >= 2


def test_external_storage_dict_with_workflow():
    """Test using external dict with workflows for custom storage mechanisms."""
    # Create an external dict that could be connected to Redis, database, etc.
    external_storage = {}

    # Create storage with external dict
    storage = InMemoryStorage(mode="workflow", storage_dict=external_storage)

    # Create workflow with external storage
    workflow = SimpleWorkflow(storage=storage, name="ExternalStorageWorkflow")

    # Run workflow
    workflow.run(query="Testing external storage with workflow")

    # Verify data is in external dict
    assert len(external_storage) == 1
    session_id = workflow.session_id
    assert session_id in external_storage
    assert external_storage[session_id]["session_id"] == session_id
    assert external_storage[session_id]["workflow_data"]["name"] == "ExternalStorageWorkflow"

    # Create another workflow instance sharing the same external storage
    workflow2 = SimpleWorkflow(
        storage=InMemoryStorage(mode="workflow", storage_dict=external_storage),
        session_id=session_id,
        name="ExternalStorageWorkflow",
    )

    # Verify workflow2 can access the previous conversation
    stored_session = workflow2.storage.read(session_id)
    assert stored_session is not None
    assert len(stored_session.memory["runs"]) > 0

    # Run workflow2 and verify external dict is updated
    workflow2.run(query="This is a follow-up workflow run")

    # Verify external dict reflects the update
    final_session_data = external_storage[session_id]
    assert len(final_session_data["memory"]["runs"]) >= 2


def test_shared_storage_across_multiple_workflows():
    """Test multiple workflows sharing the same external storage dict."""
    shared_storage = {}

    # Create multiple workflows with shared storage
    workflows = []
    for i in range(3):
        workflow = SimpleWorkflow(
            storage=InMemoryStorage(mode="workflow", storage_dict=shared_storage),
            user_id=f"user-{i}",
            workflow_id=f"workflow-{i}",
            name=f"SharedWorkflow{i}",
        )
        workflows.append(workflow)
        workflow.run(query=f"Hello from workflow {i}")

    # Verify all sessions are in shared storage
    assert len(shared_storage) == 3

    # Verify each workflow can see its own session
    for i, workflow in enumerate(workflows):
        session = workflow.storage.read(workflow.session_id)
        assert session is not None
        assert session.user_id == f"user-{i}"
        assert session.workflow_id == f"workflow-{i}"
        assert session.workflow_data["name"] == f"SharedWorkflow{i}"

    # Test filtering across shared storage
    storage = InMemoryStorage(mode="workflow", storage_dict=shared_storage)
    user_0_sessions = storage.get_all_sessions(user_id="user-0")
    assert len(user_0_sessions) == 1
    assert user_0_sessions[0].user_id == "user-0"

    workflow_1_sessions = storage.get_all_sessions(entity_id="workflow-1")
    assert len(workflow_1_sessions) == 1
    assert workflow_1_sessions[0].workflow_id == "workflow-1"
