import pytest

from agno.models.message import Message


@pytest.mark.asyncio
async def test_ashould_compact_tools_below_token_limit():
    """Test async should_compact_tools returns False when below token limit."""
    from agno.compression.manager import CompactionManager
    from agno.models.openai import OpenAIChat

    model = OpenAIChat(id="gpt-4o")
    messages = [Message(role="user", content="Hello")]

    cm = CompactionManager(compact_tools=True, compact_tools_token_limit=1000)

    sync_result = cm.should_compact_tools(messages, model=model)
    async_result = await cm.ashould_compact_tools(messages, model=model)

    assert sync_result == async_result
    assert sync_result is False


@pytest.mark.asyncio
async def test_ashould_compact_tools_above_token_limit():
    """Test async should_compact_tools returns True when above token limit."""
    from agno.compression.manager import CompactionManager
    from agno.models.openai import OpenAIChat

    model = OpenAIChat(id="gpt-4o")
    messages = [Message(role="user", content="Hello " * 100)]

    cm = CompactionManager(compact_tools=True, compact_tools_token_limit=10)

    sync_result = cm.should_compact_tools(messages, model=model)
    async_result = await cm.ashould_compact_tools(messages, model=model)

    assert sync_result == async_result
    assert sync_result is True


@pytest.mark.asyncio
async def test_ashould_compact_tools_disabled():
    """Test async should_compact_tools returns False when compression disabled."""
    from agno.compression.manager import CompactionManager
    from agno.models.openai import OpenAIChat

    model = OpenAIChat(id="gpt-4o")
    messages = [Message(role="user", content="Hello")]

    cm = CompactionManager(compact_tools=False)

    sync_result = cm.should_compact_tools(messages, model=model)
    async_result = await cm.ashould_compact_tools(messages, model=model)

    assert sync_result == async_result
    assert sync_result is False


def test_should_compact_tools_below_token_limit():
    """Test sync should_compact_tools returns False when below token limit."""
    from agno.compression.manager import CompactionManager
    from agno.models.openai import OpenAIChat

    model = OpenAIChat(id="gpt-4o")
    messages = [Message(role="user", content="Hello")]

    cm = CompactionManager(compact_tools=True, compact_tools_token_limit=1000)
    result = cm.should_compact_tools(messages, model=model)

    assert result is False


def test_should_compact_tools_above_token_limit():
    """Test sync should_compact_tools returns True when above token limit."""
    from agno.compression.manager import CompactionManager
    from agno.models.openai import OpenAIChat

    model = OpenAIChat(id="gpt-4o")
    messages = [Message(role="user", content="Hello " * 100)]

    cm = CompactionManager(compact_tools=True, compact_tools_token_limit=10)
    result = cm.should_compact_tools(messages, model=model)

    assert result is True


def test_should_compact_tools_disabled():
    """Test sync should_compact_tools returns False when compression disabled."""
    from agno.compression.manager import CompactionManager

    messages = [Message(role="user", content="Hello")]

    cm = CompactionManager(compact_tools=False)
    result = cm.should_compact_tools(messages)

    assert result is False


def test_should_compact_tools_default_count_limit():
    """Test that compact_tools_limit defaults to 3 when nothing is set."""
    from agno.compression.manager import CompactionManager

    cm = CompactionManager()
    assert cm.compact_tools_limit == 3

    cm_with_token = CompactionManager(compact_tools_token_limit=1000)
    assert cm_with_token.compact_tools_limit is None

    cm_with_count = CompactionManager(compact_tools_limit=5)
    assert cm_with_count.compact_tools_limit == 5


def test_should_compact_tools_count_based_below_limit():
    """Test should_compact_tools with count-based limit below threshold."""
    from agno.compression.manager import CompactionManager

    messages = [
        Message(role="user", content="Hello"),
        Message(role="tool", content="Result 1", tool_name="test"),
    ]

    cm = CompactionManager(compact_tools=True, compact_tools_limit=5)
    result = cm.should_compact_tools(messages)

    assert result is False


def test_should_compact_tools_count_based_above_limit():
    """Test should_compact_tools with count-based limit above threshold."""
    from agno.compression.manager import CompactionManager

    messages = [
        Message(role="user", content="Hello"),
        Message(role="tool", content="Result 1", tool_name="test1"),
        Message(role="tool", content="Result 2", tool_name="test2"),
        Message(role="tool", content="Result 3", tool_name="test3"),
    ]

    cm = CompactionManager(compact_tools=True, compact_tools_limit=2)
    result = cm.should_compact_tools(messages)

    assert result is True


def test_should_compact_tools_excludes_already_compressed():
    """Already compressed messages should not count toward the limit."""
    from agno.compression.manager import CompactionManager

    messages = [
        Message(role="user", content="Hello"),
        Message(role="tool", content="Result 1", tool_name="test1", compressed_content="compressed"),
        Message(role="tool", content="Result 2", tool_name="test2", compressed_content="compressed"),
        Message(role="tool", content="Result 3", tool_name="test3"),
    ]

    cm = CompactionManager(compact_tools=True, compact_tools_limit=2)
    result = cm.should_compact_tools(messages)

    assert result is False


@pytest.mark.asyncio
async def test_ashould_compact_tools_count_based_below_limit():
    """Test async should_compact_tools with count-based limit below threshold."""
    from agno.compression.manager import CompactionManager

    messages = [
        Message(role="user", content="Hello"),
        Message(role="tool", content="Result 1", tool_name="test"),
    ]

    cm = CompactionManager(compact_tools=True, compact_tools_limit=5)

    sync_result = cm.should_compact_tools(messages)
    async_result = await cm.ashould_compact_tools(messages)

    assert sync_result == async_result
    assert sync_result is False


@pytest.mark.asyncio
async def test_ashould_compact_tools_count_based_above_limit():
    """Test async should_compact_tools with count-based limit above threshold."""
    from agno.compression.manager import CompactionManager

    messages = [
        Message(role="user", content="Hello"),
        Message(role="tool", content="Result 1", tool_name="test1"),
        Message(role="tool", content="Result 2", tool_name="test2"),
        Message(role="tool", content="Result 3", tool_name="test3"),
    ]

    cm = CompactionManager(compact_tools=True, compact_tools_limit=2)

    sync_result = cm.should_compact_tools(messages)
    async_result = await cm.ashould_compact_tools(messages)

    assert sync_result == async_result
    assert sync_result is True
