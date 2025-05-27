import os
import tempfile
from textwrap import dedent
import uuid

import pytest

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic.claude import Claude
from agno.models.openai.chat import OpenAIChat
from agno.run.response import RunEvent
from agno.storage.sqlite import SqliteStorage
from agno.tools.decorator import tool
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools


@pytest.fixture
def temp_storage_db_file():
    """Create a temporary SQLite database file for agent storage testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def temp_memory_db_file():
    """Create a temporary SQLite database file for memory testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def agent_storage(temp_storage_db_file):
    """Create a SQLite storage for agent sessions."""
    # Use a unique table name for each test run
    table_name = f"agent_sessions_{uuid.uuid4().hex[:8]}"
    storage = SqliteStorage(table_name=table_name, db_file=temp_storage_db_file)
    storage.create()
    return storage


@pytest.fixture
def memory_db(temp_memory_db_file):
    """Create a SQLite memory database for testing."""
    db = SqliteMemoryDb(db_file=temp_memory_db_file)
    db.create()
    return db


@pytest.fixture
def memory(memory_db):
    """Create a Memory instance for testing."""
    return Memory(model=Claude(id="claude-3-5-sonnet-20241022"), db=memory_db)


def test_basic_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        monitoring=False,
    )
    
    response_generator = agent.run("Hello, how are you?", 
                                      stream=True,
                                      stream_intermediate_steps=False)
    
    event_counts = {}
    for run_response in response_generator:
        
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1
    
    assert event_counts.keys() == {RunEvent.run_response}
    
    assert event_counts[RunEvent.run_response] > 1
    
    
@pytest.mark.asyncio
async def test_async_basic_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        monitoring=False,
    )
    response_generator = await agent.arun("Hello, how are you?", 
                                      stream=True,
                                      stream_intermediate_steps=False)
    
    event_counts = {}
    async for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1
    
    assert event_counts.keys() == {RunEvent.run_response}
    
    assert event_counts[RunEvent.run_response] > 1
    

def test_basic_intermediate_steps_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        monitoring=False,
        debug_mode=True,
    )
    
    response_generator = agent.run("Hello, how are you?", 
                                      stream=True,
                                      stream_intermediate_steps=True)
    
    event_counts = {}
    for run_response in response_generator:
        print(run_response)
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1
    
    assert event_counts.keys() == {RunEvent.run_started, RunEvent.run_response, RunEvent.run_completed}
    
    assert event_counts[RunEvent.run_started] == 1
    assert event_counts[RunEvent.run_response] > 1
    assert event_counts[RunEvent.run_completed] == 1




def test_intermediate_steps_with_tools():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        telemetry=False,
        monitoring=False,
    )
    
    response_generator = agent.run("What is news in the world?", 
                                    stream=True,
                                    stream_intermediate_steps=True)
    
    event_counts = {}
    for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1
    
    assert event_counts.keys() == {RunEvent.run_started, 
                                   RunEvent.tool_call_started, 
                                   RunEvent.tool_call_completed,
                                   RunEvent.run_response, 
                                   RunEvent.run_completed}
    
    assert event_counts[RunEvent.run_started] == 1
    assert event_counts[RunEvent.run_response] > 1
    assert event_counts[RunEvent.run_completed] == 1
    assert event_counts[RunEvent.tool_call_started] == 1
    assert event_counts[RunEvent.tool_call_completed] == 1




def test_intermediate_steps_with_reasoning():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ReasoningTools(add_instructions=True)],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
        telemetry=False,
        monitoring=False,
    )
    
    response_generator = agent.run("What is the sum of the first 10 natural numbers?", 
                                    stream=True,
                                    stream_intermediate_steps=True)
    
    event_counts = {}
    for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1
    
    assert event_counts.keys() == {RunEvent.run_started, 
                                   RunEvent.tool_call_started, 
                                   RunEvent.tool_call_completed,
                                   RunEvent.reasoning_started, 
                                   RunEvent.reasoning_completed,
                                   RunEvent.reasoning_step, 
                                   RunEvent.run_response, 
                                   RunEvent.run_completed}
    
    assert event_counts[RunEvent.run_started] == 1
    assert event_counts[RunEvent.run_response] > 1
    assert event_counts[RunEvent.run_completed] == 1
    assert event_counts[RunEvent.tool_call_started] > 1
    assert event_counts[RunEvent.tool_call_completed] > 1
    assert event_counts[RunEvent.reasoning_started] == 1
    assert event_counts[RunEvent.reasoning_completed] == 1
    assert event_counts[RunEvent.reasoning_step] > 1




def test_intermediate_steps_with_user_confirmation():
    """Test that the agent streams events."""
    
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"
    
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        telemetry=False,
        monitoring=False,
    )
    
    response_generator = agent.run("What is the weather in Tokyo?", 
                                    stream=True,
                                    stream_intermediate_steps=True)
    
    # First until we hit a pause
    event_counts = {}
    for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1
    
    assert event_counts.keys() == {RunEvent.run_started, 
                                   RunEvent.run_paused}
    
    assert event_counts[RunEvent.run_started] == 1
    assert event_counts[RunEvent.run_paused] == 1
    
    assert agent.is_paused
    assert agent.run_response.tools[0].requires_confirmation
    
    # Mark the tool as confirmed
    agent.run_response.tools[0].confirmed = True
    
    # Then we continue the run
    response_generator = agent.continue_run(stream=True,
                                    stream_intermediate_steps=True)
    
    event_counts = {}
    for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1
    
    assert agent.run_response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"
    
    assert event_counts.keys() == {RunEvent.run_continued, 
                                   RunEvent.tool_call_started,
                                   RunEvent.tool_call_completed,
                                   RunEvent.run_response,
                                   RunEvent.run_completed}
    
    assert event_counts[RunEvent.run_continued] == 1
    assert event_counts[RunEvent.tool_call_started] == 1
    assert event_counts[RunEvent.tool_call_completed] == 1
    assert event_counts[RunEvent.run_response] > 1
    assert event_counts[RunEvent.run_completed] == 1
    
    assert agent.run_response.is_paused is False

    

def test_intermediate_steps_with_memory(agent_storage, memory):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory=memory,
        storage=agent_storage,
        enable_user_memories=True,
        telemetry=False,
        monitoring=False,
    )
    
    response_generator = agent.run("Hello, how are you?", 
                                      stream=True,
                                      stream_intermediate_steps=True)
    
    event_counts = {}
    for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1
    
    assert event_counts.keys() == {RunEvent.run_started, RunEvent.run_response, RunEvent.run_completed, RunEvent.updating_memory}
    
    assert event_counts[RunEvent.run_started] == 1
    assert event_counts[RunEvent.run_response] > 1
    assert event_counts[RunEvent.run_completed] == 1
    assert event_counts[RunEvent.updating_memory] == 1
