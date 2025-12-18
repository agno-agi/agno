from typing import Optional, Sequence

import pytest

from agno.agent import Agent
from agno.media import File
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools import Toolkit


class DocumentProcessingTools(Toolkit):
    """Test toolkit that accesses files without sending them to the model."""

    def __init__(self):
        super().__init__(name="document_processing_tools", tools=[self.extract_text_from_file])

    def extract_text_from_file(self, files: Optional[Sequence[File]] = None) -> str:
        """
        Extract text from uploaded files.

        This tool demonstrates that files are accessible to tools even when
        send_media_to_model=False on the agent/team.

        Args:
            files: Files passed to the agent (automatically injected)

        Returns:
            Extracted text summary
        """
        if not files:
            return "No files were provided."

        results = []
        for i, file in enumerate(files):
            if file.content:
                file_size = len(file.content)
                results.append(f"File {i + 1}: {file_size} bytes")
            else:
                results.append(f"File {i + 1}: Empty")

        return f"Processed {len(files)} file(s): " + ", ".join(results)


def create_test_file() -> File:
    """Create a test file for testing."""
    content = b"Test file content for send_media_to_model tests"
    return File(content=content, name="test.txt")


# Synchronous tests
def test_team_non_streaming_with_send_media_false(shared_db):
    """Test Team with send_media_to_model=False in non-streaming mode."""
    # Create member agent with tools
    agent = Agent(
        name="File Processor",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process uploaded files using your tools.",
        db=shared_db,
    )

    # Create team with send_media_to_model=False
    team = Team(
        name="File Processing Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        send_media_to_model=False,
        instructions="Delegate file processing to the File Processor agent.",
        db=shared_db,
    )

    # Create test file
    test_file = create_test_file()

    # Run team - should work without sending files to model
    response = team.run(
        input="Process the uploaded file.",
        files=[test_file],
        stream=False,
    )

    # Verify response was generated
    assert response is not None
    assert response.content is not None

    # Verify member agent has send_media_to_model=False set
    assert agent.send_media_to_model is False


def test_team_streaming_with_send_media_false(shared_db):
    """Test Team with send_media_to_model=False in streaming mode."""
    # Create member agent with tools
    agent = Agent(
        name="File Processor",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process uploaded files using your tools.",
        db=shared_db,
    )

    # Create team with send_media_to_model=False
    team = Team(
        name="File Processing Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        send_media_to_model=False,
        instructions="Delegate file processing to the File Processor agent.",
        db=shared_db,
    )

    # Create test file
    test_file = create_test_file()

    # Run team in streaming mode
    events = []
    for event in team.run(
        input="Process the uploaded file.",
        files=[test_file],
        stream=True,
    ):
        events.append(event)

    # Verify we got events
    assert len(events) > 0

    # Verify member agent has send_media_to_model=False set
    assert agent.send_media_to_model is False


def test_team_with_multiple_members(shared_db):
    """Test Team with multiple members and send_media_to_model=False."""
    # Create multiple member agents
    processor = Agent(
        name="Processor",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process files.",
        db=shared_db,
    )

    analyzer = Agent(
        name="Analyzer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Analyze results.",
        db=shared_db,
    )

    # Create team with send_media_to_model=False
    team = Team(
        name="Multi-Agent Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[processor, analyzer],
        send_media_to_model=False,
        instructions="Delegate to appropriate agents.",
        db=shared_db,
    )

    # Create test file
    test_file = create_test_file()

    # Run team
    response = team.run(
        input="Process and analyze the file.",
        files=[test_file],
        stream=False,
    )

    # Verify response
    assert response is not None
    assert response.content is not None

    # Verify both members have send_media_to_model=False set
    assert processor.send_media_to_model is False
    assert analyzer.send_media_to_model is False


def test_team_without_files(shared_db):
    """Test that Team works normally without files."""
    # Create member agent
    agent = Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Be helpful.",
        db=shared_db,
    )

    # Create team with send_media_to_model=False
    team = Team(
        name="Helper Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        send_media_to_model=False,
        instructions="Help with tasks.",
        db=shared_db,
    )

    # Run team without files
    response = team.run(
        input="Say hello.",
        stream=False,
    )

    # Verify response
    assert response is not None
    assert response.content is not None


def test_member_agent_setting_across_multiple_runs(shared_db):
    """Test that member agent settings are applied correctly across multiple runs."""
    # Create member agent with send_media_to_model=True
    agent = Agent(
        name="File Processor",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process files.",
        send_media_to_model=True,
        db=shared_db,
    )

    # Create team with send_media_to_model=False
    team = Team(
        name="File Processing Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        send_media_to_model=False,
        instructions="Delegate file processing.",
        db=shared_db,
    )

    # Create test file
    test_file = create_test_file()

    # Run team first time
    response1 = team.run(
        input="Process the file.",
        files=[test_file],
        stream=False,
    )

    # Verify member agent has send_media_to_model=False after first run
    assert agent.send_media_to_model is False

    # Run team second time
    response2 = team.run(
        input="Process another file.",
        files=[test_file],
        stream=False,
    )

    # Verify member agent still has send_media_to_model=False after second run
    assert agent.send_media_to_model is False

    # Verify both responses are valid
    assert response1 is not None
    assert response2 is not None


# Asynchronous tests


@pytest.mark.asyncio
async def test_team_async_non_streaming_with_send_media_false(shared_db):
    """Test Team with send_media_to_model=False in async non-streaming mode."""
    # Create member agent with tools
    agent = Agent(
        name="File Processor",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process uploaded files using your tools.",
        db=shared_db,
    )

    # Create team with send_media_to_model=False
    team = Team(
        name="File Processing Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        send_media_to_model=False,
        instructions="Delegate file processing to the File Processor agent.",
        db=shared_db,
    )

    # Create test file
    test_file = create_test_file()

    # Run team asynchronously
    response = await team.arun(
        input="Process the uploaded file.",
        files=[test_file],
        stream=False,
    )

    # Verify response was generated
    assert response is not None
    assert response.content is not None

    # Verify member agent has send_media_to_model=False set
    assert agent.send_media_to_model is False


@pytest.mark.asyncio
async def test_team_async_streaming_with_send_media_false(shared_db):
    """Test Team with send_media_to_model=False in async streaming mode."""
    # Create member agent with tools
    agent = Agent(
        name="File Processor",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process uploaded files using your tools.",
        db=shared_db,
    )

    # Create team with send_media_to_model=False
    team = Team(
        name="File Processing Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        send_media_to_model=False,
        instructions="Delegate file processing to the File Processor agent.",
        db=shared_db,
    )

    # Create test file
    test_file = create_test_file()

    # Run team in async streaming mode
    events = []
    async for event in team.arun(
        input="Process the uploaded file.",
        files=[test_file],
        stream=True,
    ):
        events.append(event)

    # Verify we got events
    assert len(events) > 0

    # Verify member agent has send_media_to_model=False set
    assert agent.send_media_to_model is False


@pytest.mark.asyncio
async def test_team_async_delegate_to_all_members(shared_db):
    """Test Team with delegate_to_all_members=True and send_media_to_model=False."""
    # Create multiple member agents
    processor1 = Agent(
        name="Processor 1",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process files.",
        db=shared_db,
    )

    processor2 = Agent(
        name="Processor 2",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process files.",
        db=shared_db,
    )

    # Create team with delegate_to_all_members=True
    team = Team(
        name="Parallel Processing Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[processor1, processor2],
        send_media_to_model=False,
        delegate_to_all_members=True,
        instructions="Process files in parallel.",
        db=shared_db,
    )

    # Create test file
    test_file = create_test_file()

    # Run team
    response = await team.arun(
        input="Process the file.",
        files=[test_file],
        stream=False,
    )

    # Verify response
    assert response is not None
    assert response.content is not None

    # Verify both members have send_media_to_model=False set
    assert processor1.send_media_to_model is False
    assert processor2.send_media_to_model is False


@pytest.mark.asyncio
async def test_team_async_delegate_to_all_members_streaming(shared_db):
    """Test Team with delegate_to_all_members=True in async streaming mode."""
    # Create multiple member agents
    processor1 = Agent(
        name="Processor 1",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process files.",
        db=shared_db,
    )

    processor2 = Agent(
        name="Processor 2",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DocumentProcessingTools()],
        instructions="Process files.",
        db=shared_db,
    )

    # Create team with delegate_to_all_members=True
    team = Team(
        name="Parallel Processing Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[processor1, processor2],
        send_media_to_model=False,
        delegate_to_all_members=True,
        instructions="Process files in parallel.",
        db=shared_db,
    )

    # Create test file
    test_file = create_test_file()

    # Run team with streaming
    events = []
    async for event in team.arun(
        input="Process the file.",
        files=[test_file],
        stream=True,
    ):
        events.append(event)

    # Verify we got events
    assert len(events) > 0

    # Verify both members have send_media_to_model=False set
    assert processor1.send_media_to_model is False
    assert processor2.send_media_to_model is False
