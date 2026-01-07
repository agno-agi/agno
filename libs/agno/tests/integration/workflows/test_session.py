import uuid
from typing import Any, Dict, Optional

import pytest

from agno.agent.agent import Agent
from agno.run import RunContext
from agno.workflow import Step, StepInput, StepOutput, Workflow
from agno.workflow.condition import Condition
from agno.workflow.router import Router

# Simple helper functions


def research_step_function(step_input: StepInput) -> StepOutput:
    """Minimal research function."""
    topic = step_input.input
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
    def add_item(run_context: RunContext, item: str) -> str:
        """Add an item to the shopping list."""
        run_context.session_state["shopping_list"].append(item)
        return f"The shopping list is now {run_context.session_state['shopping_list']}"

    def get_all_items(run_context: RunContext) -> str:
        """Get all items from the shopping list."""
        return f"The shopping list is now {run_context.session_state['shopping_list']}"

    workflow = workflow_factory(shared_db, session_id="session_1", session_state={"shopping_list": []})

    workflow.steps[0] = Step(name="add_item", agent=Agent(tools=[add_item]))
    workflow.steps[1] = Step(
        name="list_items", agent=Agent(tools=[get_all_items], instructions="Get all items from the shopping list")
    )

    # Create an Agent that maintains state
    workflow.run("Add oranges to my shopping list", session_id="session_1", session_state={"shopping_list": []})

    session_from_storage = workflow.get_session(session_id="session_1")
    assert session_from_storage.session_data["session_state"] == {"shopping_list": ["oranges"]}


def test_condition_with_session_state(shared_db):
    """Test that Condition evaluators can access and modify session_state."""
    session_id = "session_condition"

    # Track if condition was called with session_state
    condition_calls = []

    def condition_evaluator(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
        """Condition evaluator that uses session_state."""
        condition_calls.append(
            {
                "user_id": session_state.get("current_user_id"),
                "session_id": session_state.get("current_session_id"),
                "counter": session_state.get("counter", 0),
            }
        )

        # Increment counter
        session_state["counter"] = session_state.get("counter", 0) + 1
        session_state["condition_executed"] = True

        # Return True if counter is less than 2
        return session_state["counter"] < 2

    def dummy_function(step_input: StepInput) -> StepOutput:
        return StepOutput(content="Dummy step executed")

    workflow = Workflow(
        name="Condition Test Workflow",
        db=shared_db,
        session_id=session_id,
        session_state={"counter": 0},
        steps=[
            Condition(
                name="Test Condition",
                description="Test condition with session_state",
                evaluator=condition_evaluator,
                steps=[
                    Step(name="dummy", executor=dummy_function),
                ],
            ),
        ],
    )

    # First run - condition should be True
    response1 = workflow.run("Test 1", session_id=session_id)
    assert response1.run_id is not None

    # Verify condition was called with session_state
    assert len(condition_calls) == 1
    assert condition_calls[0]["session_id"] == session_id
    assert condition_calls[0]["counter"] == 0

    # Verify session state was modified
    session_state = workflow.get_session_state(session_id=session_id)
    assert session_state["counter"] == 1
    assert session_state["condition_executed"] is True

    # Second run - condition should be False
    response2 = workflow.run("Test 2", session_id=session_id)
    assert response2.run_id is not None

    # Verify condition was called again
    assert len(condition_calls) == 2
    assert condition_calls[1]["counter"] == 1

    # Verify counter was incremented again
    session_state = workflow.get_session_state(session_id=session_id)
    assert session_state["counter"] == 2


def test_router_with_session_state(shared_db):
    """Test that Router selectors can access and modify session_state."""
    session_id = "session_router"

    # Track router calls
    router_calls = []

    def router_selector(step_input: StepInput, session_state: Dict[str, Any]) -> Step:
        """Router selector that uses session_state."""
        router_calls.append(
            {
                "user_id": session_state.get("current_user_id"),
                "session_id": session_state.get("current_session_id"),
                "route_count": session_state.get("route_count", 0),
            }
        )

        # Increment route count
        session_state["route_count"] = session_state.get("route_count", 0) + 1
        session_state["router_executed"] = True

        # Route based on count
        if session_state["route_count"] % 2 == 1:
            return step_a
        else:
            return step_b

    def step_a_function(step_input: StepInput) -> StepOutput:
        return StepOutput(content="Step A executed")

    def step_b_function(step_input: StepInput) -> StepOutput:
        return StepOutput(content="Step B executed")

    step_a = Step(name="step_a", executor=step_a_function)
    step_b = Step(name="step_b", executor=step_b_function)

    workflow = Workflow(
        name="Router Test Workflow",
        db=shared_db,
        session_id=session_id,
        session_state={"route_count": 0},
        steps=[
            Router(
                name="Test Router",
                description="Test router with session_state",
                selector=router_selector,
                choices=[step_a, step_b],
            ),
        ],
    )

    # First run - should route to step_a
    response1 = workflow.run("Test 1", session_id=session_id)
    assert response1.run_id is not None
    assert "Step A executed" in response1.content

    # Verify router was called with session_state
    assert len(router_calls) == 1
    assert router_calls[0]["session_id"] == session_id
    assert router_calls[0]["route_count"] == 0

    # Verify session state was modified
    session_state = workflow.get_session_state(session_id=session_id)
    assert session_state["route_count"] == 1
    assert session_state["router_executed"] is True

    # Second run - should route to step_b
    response2 = workflow.run("Test 2", session_id=session_id)
    assert response2.run_id is not None
    assert "Step B executed" in response2.content

    # Verify router was called again
    assert len(router_calls) == 2
    assert router_calls[1]["route_count"] == 1

    # Verify route count was incremented
    session_state = workflow.get_session_state(session_id=session_id)
    assert session_state["route_count"] == 2


def test_condition_without_session_state_param(shared_db):
    """Test that Condition evaluators still work without session_state parameter."""
    session_id = "session_condition_no_param"

    def condition_evaluator_no_param(step_input: StepInput) -> bool:
        """Condition evaluator without session_state parameter."""
        # This should still work
        return True

    def dummy_function(step_input: StepInput) -> StepOutput:
        return StepOutput(content="Dummy step executed")

    workflow = Workflow(
        name="Condition No Param Test",
        db=shared_db,
        session_id=session_id,
        steps=[
            Condition(
                name="Test Condition",
                evaluator=condition_evaluator_no_param,
                steps=[
                    Step(name="dummy", executor=dummy_function),
                ],
            ),
        ],
    )

    # Should work without error
    response = workflow.run("Test", session_id=session_id)
    assert response.run_id is not None
    assert "Dummy step executed" in response.content


def test_router_without_session_state_param(shared_db):
    """Test that Router selectors still work without session_state parameter."""
    session_id = "session_router_no_param"

    def router_selector_no_param(step_input: StepInput) -> Step:
        """Router selector without session_state parameter."""
        # This should still work
        return step_a

    def step_a_function(step_input: StepInput) -> StepOutput:
        return StepOutput(content="Step A executed")

    step_a = Step(name="step_a", executor=step_a_function)

    workflow = Workflow(
        name="Router No Param Test",
        db=shared_db,
        session_id=session_id,
        steps=[
            Router(
                name="Test Router",
                selector=router_selector_no_param,
                choices=[step_a],
            ),
        ],
    )

    # Should work without error
    response = workflow.run("Test", session_id=session_id)
    assert response.run_id is not None
    assert "Step A executed" in response.content


async def test_async_condition_with_session_state(async_shared_db):
    """Test that async Condition evaluators can access and modify session_state."""
    session_id = "session_async_condition"

    condition_calls = []

    async def async_condition_evaluator(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
        """Async condition evaluator that uses session_state."""
        condition_calls.append(
            {
                "session_id": session_state.get("current_session_id"),
                "async_counter": session_state.get("async_counter", 0),
            }
        )

        session_state["async_counter"] = session_state.get("async_counter", 0) + 1
        session_state["async_condition_executed"] = True

        return session_state["async_counter"] < 2

    def dummy_function(step_input: StepInput) -> StepOutput:
        return StepOutput(content="Async dummy executed")

    workflow = Workflow(
        name="Async Condition Test",
        db=async_shared_db,
        session_id=session_id,
        session_state={"async_counter": 0},
        steps=[
            Condition(
                name="Async Condition",
                evaluator=async_condition_evaluator,
                steps=[
                    Step(name="dummy", executor=dummy_function),
                ],
            ),
        ],
    )

    # First run
    response1 = await workflow.arun("Test 1", session_id=session_id)
    assert response1.run_id is not None

    # Verify async condition was called
    assert len(condition_calls) == 1
    assert condition_calls[0]["async_counter"] == 0

    # Verify state was modified (use async method with AsyncSqliteDb)
    session_state = await workflow.aget_session_state(session_id=session_id)
    assert session_state["async_counter"] == 1
    assert session_state["async_condition_executed"] is True


async def test_async_router_with_session_state(async_shared_db):
    """Test that async Router selectors can access and modify session_state."""
    session_id = "session_async_router"

    router_calls = []

    async def async_router_selector(step_input: StepInput, session_state: Dict[str, Any]) -> Step:
        """Async router selector that uses session_state."""
        router_calls.append(
            {
                "session_id": session_state.get("current_session_id"),
                "async_route_count": session_state.get("async_route_count", 0),
            }
        )

        session_state["async_route_count"] = session_state.get("async_route_count", 0) + 1
        session_state["async_router_executed"] = True

        return step_a

    def step_a_function(step_input: StepInput) -> StepOutput:
        return StepOutput(content="Async Step A executed")

    step_a = Step(name="step_a", executor=step_a_function)

    workflow = Workflow(
        name="Async Router Test",
        db=async_shared_db,
        session_id=session_id,
        session_state={"async_route_count": 0},
        steps=[
            Router(
                name="Async Router",
                selector=async_router_selector,
                choices=[step_a],
            ),
        ],
    )

    # First run
    response1 = await workflow.arun("Test 1", session_id=session_id)
    assert response1.run_id is not None
    assert "Async Step A executed" in response1.content

    # Verify async router was called
    assert len(router_calls) == 1
    assert router_calls[0]["async_route_count"] == 0

    # Verify state was modified (use async method with AsyncSqliteDb)
    session_state = await workflow.aget_session_state(session_id=session_id)
    assert session_state["async_route_count"] == 1
    assert session_state["async_router_executed"] is True


async def test_workflow_with_base_model_content(shared_db):
    """Test that a workflow with a BaseModel content can be run."""

    from datetime import datetime

    from pydantic import BaseModel

    from agno.db.base import SessionType

    session_id = "session_base_model_content"

    class Content(BaseModel):
        content: str
        date: datetime

    def content_function(step_input: StepInput) -> StepOutput:
        return StepOutput(content=Content(content="Hello World", date=datetime.now()))

    workflow = Workflow(
        name="Base Model Content Test",
        db=shared_db,
        steps=[
            Step(name="content", executor=content_function),
        ],
    )

    response = workflow.run("Test", session_id=session_id)
    assert response.run_id is not None
    assert response.content.content == "Hello World"
    assert response.content.date is not None
    assert (
        shared_db.get_session(session_id=session_id, session_type=SessionType.WORKFLOW) is not None
    )  # This tells us that the session was stored in the database with the BaseModel content with values like datetime


@pytest.mark.asyncio
async def test_async_workflow_run_with_async_db(async_shared_db):
    """Test Workflow async arun() with async database."""
    workflow = Workflow(
        name="Test Workflow",
        db=async_shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    session_id = str(uuid.uuid4())
    response = await workflow.arun("Test", session_id=session_id)
    assert response is not None
    assert response.run_id is not None


@pytest.mark.asyncio
async def test_async_workflow_run_stream_with_async_db(async_shared_db):
    """Test Workflow async arun() streaming with async database."""
    workflow = Workflow(
        name="Test Workflow",
        db=async_shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    session_id = str(uuid.uuid4())
    final_response = None
    async for response in workflow.arun("Test", session_id=session_id, stream=True):
        final_response = response

    assert final_response is not None
    assert final_response.run_id is not None


@pytest.mark.asyncio
async def test_aget_session_with_async_db(async_shared_db):
    """Test aget_session with async database."""
    workflow = Workflow(
        name="Test Workflow",
        db=async_shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    session_id = str(uuid.uuid4())
    await workflow.arun("Test", session_id=session_id)

    session = await workflow.aget_session(session_id=session_id)
    assert session is not None
    assert session.session_id == session_id
    assert len(session.runs) == 1


@pytest.mark.asyncio
async def test_asave_session_with_async_db(async_shared_db):
    """Test asave_session with async database."""
    workflow = Workflow(
        name="Test Workflow",
        db=async_shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    session_id = str(uuid.uuid4())
    await workflow.arun("Test", session_id=session_id)

    session = await workflow.aget_session(session_id=session_id)
    session.session_data["custom_key"] = "custom_value"

    await workflow.asave_session(session)

    retrieved_session = await workflow.aget_session(session_id=session_id)
    assert retrieved_session.session_data["custom_key"] == "custom_value"


@pytest.mark.asyncio
async def test_aset_session_name_with_async_db(async_shared_db):
    """Test aset_session_name with async database."""
    workflow = Workflow(
        name="Test Workflow",
        db=async_shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    session_id = str(uuid.uuid4())
    await workflow.arun("Test", session_id=session_id)

    await workflow.aset_session_name(session_id=session_id, session_name="my_test_session")

    session = await workflow.aget_session(session_id=session_id)
    assert session.session_data["session_name"] == "my_test_session"


@pytest.mark.asyncio
async def test_aget_session_name_with_async_db(async_shared_db):
    """Test aget_session_name with async database."""
    workflow = Workflow(
        name="Test Workflow",
        db=async_shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    session_id = str(uuid.uuid4())
    await workflow.arun("Test", session_id=session_id)

    await workflow.aset_session_name(session_id=session_id, session_name="my_test_session")

    session_name = await workflow.aget_session_name(session_id=session_id)
    assert session_name == "my_test_session"


@pytest.mark.asyncio
async def test_aget_session_state_with_async_db(async_shared_db):
    """Test aget_session_state with async database."""
    workflow = Workflow(
        name="Test Workflow",
        db=async_shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    session_id = str(uuid.uuid4())
    await workflow.arun("Test", session_id=session_id, session_state={"key": "value"})

    session_state = await workflow.aget_session_state(session_id=session_id)
    assert session_state is not None


@pytest.mark.asyncio
async def test_aupdate_session_state_with_async_db(async_shared_db):
    """Test aupdate_session_state with async database."""
    workflow = Workflow(
        name="Test Workflow",
        db=async_shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    session_id = str(uuid.uuid4())
    await workflow.arun("Test", session_id=session_id, session_state={"counter": 0, "items": []})

    result = await workflow.aupdate_session_state({"counter": 10}, session_id=session_id)
    assert result == {"counter": 10, "items": []}

    updated_state = await workflow.aget_session_state(session_id=session_id)
    assert updated_state["counter"] == 10


@pytest.mark.asyncio
async def test_adelete_session_with_async_db(async_shared_db):
    """Test adelete_session with async database."""
    workflow = Workflow(
        name="Test Workflow",
        db=async_shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    session_id = str(uuid.uuid4())
    await workflow.arun("Test", session_id=session_id)

    session = await workflow.aget_session(session_id=session_id)
    assert session is not None

    await workflow.adelete_session(session_id=session_id)

    session = await workflow.aget_session(session_id=session_id)
    assert session is None
