from typing import Any, Dict, Optional

from agno.agent.agent import Agent
from agno.workflow import Step, StepInput, StepOutput, Workflow

# Simple helper functions


def research_step_function(step_input: StepInput) -> StepOutput:
    """Minimal research function."""
    topic = step_input.message
    return StepOutput(content=f"Research: {topic}")


def content_step_function(step_input: StepInput) -> StepOutput:
    """Minimal content function."""
    prev = step_input.previous_step_content
    return StepOutput(content=f"Content: Hello World | Referencing: {prev}")


def workflow_factory(shared_db, session_id: Optional[str] = None, session_state: Optional[Dict[str, Any]] = None):
    """Create a route team with storage and memory for testing."""
    return Workflow(
        name="Test Workflow",
        db=shared_db,
        session_id=session_id,
        session_state=session_state,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )


def test_workflow_default_state(shared_db):
    session_id = "session_1"
    session_state = {"test_key": "test_value"}

    workflow = workflow_factory(shared_db, session_id, session_state)

    response = workflow.run("Test")

    assert response.run_id is not None
    assert workflow.session_id == session_id
    assert workflow.session_state == session_state

    session_from_storage = workflow.get_session(session_id=session_id)
    assert session_from_storage is not None
    assert session_from_storage.session_id == session_id
    assert session_from_storage.session_data["session_state"] == session_state


def test_workflow_set_session_name(shared_db):
    session_id = "session_1"
    session_state = {"test_key": "test_value"}

    workflow = workflow_factory(shared_db, session_id, session_state)

    workflow.run("Test")

    workflow.set_session_name(session_id=session_id, session_name="my_test_session")

    session_from_storage = workflow.get_session(session_id=session_id)
    assert session_from_storage is not None
    assert session_from_storage.session_id == session_id
    assert session_from_storage.session_data["session_name"] == "my_test_session"


def test_workflow_get_session_name(shared_db):
    session_id = "session_1"
    workflow = workflow_factory(shared_db, session_id)
    workflow.run("Test")
    workflow.set_session_name(session_id=session_id, session_name="my_test_session")
    assert workflow.get_session_name() == "my_test_session"


def test_workflow_get_session_state(shared_db):
    session_id = "session_1"
    workflow = workflow_factory(shared_db, session_id, session_state={"test_key": "test_value"})
    workflow.run("Test")
    assert workflow.get_session_state() == {"test_key": "test_value"}


def test_workflow_session_state_switch_session_id(shared_db):
    session_id_1 = "session_1"
    session_id_2 = "session_2"
    session_state = {"test_key": "test_value"}

    workflow = workflow_factory(shared_db, session_id_1, session_state)

    # First run with a different session ID
    workflow.run("Test 1", session_id=session_id_1)
    session_from_storage = workflow.get_session(session_id=session_id_1)
    assert session_from_storage.session_id == session_id_1
    assert session_from_storage.session_data["session_state"] == session_state

    # Second run with different session ID
    workflow.run("Test", session_id=session_id_2)
    session_from_storage = workflow.get_session(session_id=session_id_2)
    assert session_from_storage.session_id == session_id_2
    assert session_from_storage.session_data["session_state"] == session_state

    # Third run with the original session ID
    workflow.run("Test", session_id=session_id_1)
    session_from_storage = workflow.get_session(session_id=session_id_1)
    assert session_from_storage.session_id == session_id_1
    assert session_from_storage.session_data["session_state"] == {"test_key": "test_value"}


def test_workflow_with_state_shared_downstream(shared_db):
    # Define a tool that increments our counter and returns the new value
    def add_item(session_state: Dict[str, Any], item: str) -> str:
        """Add an item to the shopping list."""
        session_state["shopping_list"].append(item)
        return f"The shopping list is now {session_state['shopping_list']}"

    def get_all_items(session_state: Dict[str, Any]) -> str:
        """Get all items from the shopping list."""
        return f"The shopping list is now {session_state['shopping_list']}"

    workflow = workflow_factory(shared_db, session_id="session_1", session_state={"shopping_list": []})

    workflow.steps[0] = Step(name="add_item", agent=Agent(tools=[add_item]))
    workflow.steps[1] = Step(
        name="list_items", agent=Agent(tools=[get_all_items], instructions="Get all items from the shopping list")
    )

    # Create an Agent that maintains state
    workflow.run("Add oranges to my shopping list", session_id="session_1", session_state={"shopping_list": []})

    session_from_storage = workflow.get_session(session_id="session_1")
    assert session_from_storage.session_data["session_state"] == {"shopping_list": ["oranges"]}
