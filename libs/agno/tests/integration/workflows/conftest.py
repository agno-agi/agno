import asyncio
import uuid
from typing import List

import pytest
import pytest_asyncio

from agno.agent.agent import Agent
from agno.db.json import JsonDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.workflow import Condition, Loop, Parallel, Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Skip tests that hit rate limits (429) instead of failing.

    Checks both the exception message and the full test report (which includes
    captured stdout/stderr with agent error logs) for rate limit indicators.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        if call.excinfo is not None:
            error_msg = str(call.excinfo.value)
            full_repr = str(report.longrepr) if report.longrepr else ""
            sections_text = " ".join(content for _, content in report.sections)
            combined = (error_msg + full_repr + sections_text).lower()
            if any(p in combined for p in ["429", "rate limit", "rate_limit", "quota", "resource_exhausted"]):
                report.outcome = "skipped"
                report.longrepr = ("", -1, "Skipped: rate limit (429)")


@pytest.fixture
def test_agent():
    """Create minimal test agent."""
    return Agent(name="TestAgent", instructions="Test agent for testing.")


@pytest.fixture
def test_team(test_agent):
    """Create minimal test team."""
    return Team(name="TestTeam", members=[test_agent])


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing"""
    return Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a test agent. Respond with 'Test response from agent'",
    )


@pytest.fixture
def mock_team(mock_agent):
    """Create a mock agent for testing"""
    return Team(
        name="Test Team",
        members=[mock_agent],
    )


@pytest.fixture
def agent_with_db(tmp_path):
    """Create a simple Agent with a db for testing"""
    db = JsonDb(session_table="workflow_session", db_path=str(tmp_path / "workflow_bg_test"))
    return Agent(name="Test Agent with DB", instructions="Test agent for testing.", db=db)


@pytest_asyncio.fixture
async def async_shared_db(temp_storage_db_file):
    """Create an async SQLite storage for sessions."""
    # Use a unique table name for each test run
    table_name = f"sessions_{uuid.uuid4().hex[:8]}"
    db = AsyncSqliteDb(session_table=table_name, db_file=temp_storage_db_file)

    # Initialize tables before using
    await db._create_all_tables()

    return db


@pytest.fixture
def simple_workflow(mock_agent, tmp_path):
    """Create a simple workflow for testing"""
    db = JsonDb(session_table="workflow_session", db_path=str(tmp_path / "workflow_bg_test"))

    return Workflow(
        name="Test Background Workflow",
        description="Simple workflow for background execution testing",
        db=db,
        steps=[
            Step(name="Test Step", agent=mock_agent),
        ],
    )


@pytest_asyncio.fixture
async def simple_workflow_with_async_db(mock_agent, tmp_path):
    """Create a simple workflow for testing with async database"""
    db = AsyncSqliteDb(session_table="workflow_session", db_file=str(tmp_path / "workflow_bg_test.db"))

    # Initialize tables before using
    await db._create_all_tables()

    return Workflow(
        name="Test Background Workflow with Async DB",
        description="Simple workflow for background execution testing with async database",
        db=db,
        steps=[
            Step(name="Test Step", agent=mock_agent),
        ],
    )


@pytest.fixture
def multi_step_workflow(mock_agent, shared_db):
    """Create a multi-step workflow for testing"""
    agent2 = Agent(
        name="Second Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are the second test agent. Respond with 'Second response'",
    )

    return Workflow(
        name="Multi-Step Background Workflow",
        description="Multi-step workflow for background execution testing",
        db=shared_db,
        steps=[
            Step(name="First Step", agent=mock_agent),
            Step(name="Second Step", agent=agent2),
        ],
    )


@pytest.fixture
def team_workflow(tmp_path):
    """Create a workflow with team for testing"""
    db = JsonDb(session_table="workflow_session", db_path=str(tmp_path / "workflow_bg_team_test"))

    agent1 = Agent(
        name="Team Member 1",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are team member 1. Provide analysis.",
    )

    agent2 = Agent(
        name="Team Member 2",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are team member 2. Provide synthesis.",
    )

    team = Team(
        name="Test Team",
        members=[agent1, agent2],
        instructions="Work together to analyze the topic",
    )

    return Workflow(
        name="Team Background Workflow",
        description="Team-based workflow for background execution testing",
        db=db,
        steps=[
            Step(name="Team Analysis", team=team),
        ],
    )


@pytest.fixture
def custom_function_workflow(tmp_path):
    """Create a workflow with custom function for testing"""
    db = JsonDb(session_table="workflow_session", db_path=str(tmp_path / "workflow_bg_func_test"))

    async def custom_async_function(workflow, execution_input):
        """Custom async function that simulates work"""
        await asyncio.sleep(0.1)  # Simulate some work
        return f"Custom function processed: {execution_input.input}"

    return Workflow(
        name="Custom Function Background Workflow",
        description="Custom function workflow for background execution testing",
        db=db,
        steps=custom_async_function,
    )


@pytest.fixture
def condition_workflow(mock_agent, tmp_path):
    """Create a workflow with conditional execution for testing"""
    db = JsonDb(session_table="workflow_session", db_path=str(tmp_path / "workflow_bg_condition_test"))

    fact_checker = Agent(
        name="Fact Checker",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a fact checker. Verify the information provided.",
    )

    def needs_fact_checking(step_input: StepInput) -> bool:
        """Determine if content needs fact-checking"""
        return True

    return Workflow(
        name="Conditional Background Workflow",
        description="Workflow with conditional execution for background testing",
        db=db,
        steps=[
            Step(name="Initial Research", agent=mock_agent),
            Condition(
                name="Fact Check Condition",
                description="Check if fact-checking is needed",
                evaluator=needs_fact_checking,
                steps=[Step(name="Fact Check", agent=fact_checker)],
            ),
            Step(name="Final Summary", agent=mock_agent),
        ],
    )


@pytest.fixture
def parallel_workflow(tmp_path):
    """Create a workflow with parallel execution for testing"""
    db = JsonDb(session_table="workflow_session", db_path=str(tmp_path / "workflow_bg_parallel_test"))

    researcher1 = Agent(
        name="Researcher 1",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are researcher 1. Focus on technical aspects.",
    )

    researcher2 = Agent(
        name="Researcher 2",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are researcher 2. Focus on market aspects.",
    )

    writer = Agent(
        name="Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a writer. Combine research into an article.",
    )

    return Workflow(
        name="Parallel Background Workflow",
        description="Workflow with parallel execution for background testing",
        db=db,
        steps=[
            Parallel(
                Step(name="Technical Research", agent=researcher1),
                Step(name="Market Research", agent=researcher2),
                name="Research Phase",
            ),
            Step(name="Write Article", agent=writer),
        ],
    )


@pytest.fixture
def router_workflow(tmp_path):
    """Create a workflow with router for testing"""
    db = JsonDb(session_table="workflow_session", db_path=str(tmp_path / "workflow_bg_router_test"))

    tech_agent = Agent(
        name="Tech Specialist",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a tech specialist. Focus on technical topics.",
    )

    general_agent = Agent(
        name="General Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a general researcher. Handle broad topics.",
    )

    writer = Agent(
        name="Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a writer. Create content based on research.",
    )

    def research_router(step_input: StepInput) -> List[Step]:
        """Route based on topic content"""
        topic = step_input.input or ""
        tech_keywords = ["ai", "machine learning", "programming", "software", "tech", "computer"]

        if any(keyword in topic.lower() for keyword in tech_keywords):
            return [Step(name="Tech Research", agent=tech_agent)]
        else:
            return [Step(name="General Research", agent=general_agent)]

    return Workflow(
        name="Router Background Workflow",
        description="Workflow with router for background testing",
        db=db,
        steps=[
            Router(
                name="Research Router",
                selector=research_router,
                choices=[
                    Step(name="Tech Research", agent=tech_agent),
                    Step(name="General Research", agent=general_agent),
                ],
            ),
            Step(name="Write Content", agent=writer),
        ],
    )


@pytest.fixture
def loop_workflow(tmp_path):
    """Create a workflow with loop for testing"""
    db = JsonDb(session_table="workflow_session", db_path=str(tmp_path / "workflow_bg_loop_test"))

    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a researcher. Provide research findings.",
    )

    content_creator = Agent(
        name="Content Creator",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a content creator. Create final content.",
    )

    def research_evaluator(outputs: List[StepOutput]) -> bool:
        """Evaluate if research is sufficient"""
        if not outputs:
            return False
        # Simple condition: check if we have substantial content
        for output in outputs:
            if output.content and len(output.content) > 50:
                return True
        return False

    return Workflow(
        name="Loop Background Workflow",
        description="Workflow with loop for background testing",
        db=db,
        steps=[
            Loop(
                name="Research Loop",
                steps=[Step(name="Research Step", agent=researcher)],
                end_condition=research_evaluator,
                max_iterations=2,
            ),
            Step(name="Create Content", agent=content_creator),
        ],
    )
