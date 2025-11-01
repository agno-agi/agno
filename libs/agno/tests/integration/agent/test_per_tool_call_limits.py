import pytest
import pytest_asyncio

from agno.agent.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.run.agent import RunEvent
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.lancedb.lance_db import LanceDb
from agno.vectordb.search import SearchType


def test_per_tool_call_limit():
    yfinance_tools = YFinanceTools(cache_results=True)

    for tool in yfinance_tools.functions.values():
        if tool.name == "get_current_stock_price":
            tool.call_limit = 1
            break

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[yfinance_tools],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Find me the current price of TSLA and APPL.")

    # Verify that get_current_stock_price was only called once due to per_tool_call_limit
    stock_price_calls = [t for t in response.tools if t.tool_name == "get_current_stock_price"]
    assert len(stock_price_calls) == 1
    assert stock_price_calls[0].tool_args == {"symbol": "TSLA"}
    assert stock_price_calls[0].result is not None
    assert response.content is not None


def test_per_tool_call_limit_stream():
    yfinance_tools = YFinanceTools(cache_results=True)

    for tool in yfinance_tools.functions.values():
        if tool.name == "get_current_stock_price":
            tool.call_limit = 1
            break

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[yfinance_tools],
        markdown=True,
        telemetry=False,
    )

    response_stream = agent.run("Find me the current price of TSLA and APPL.", stream=True, stream_events=True)

    tools = []
    for chunk in response_stream:
        if chunk.event == RunEvent.tool_call_completed:
            tools.append(chunk.tool)

    stock_price_calls = [t for t in tools if t.tool_name == "get_current_stock_price"]
    assert len(stock_price_calls) == 1, f"Expected 1 stock price call, got {len(stock_price_calls)}"
    assert stock_price_calls[0].tool_args == {"symbol": "TSLA"}
    assert stock_price_calls[0].result is not None


@pytest.mark.asyncio
async def test_per_tool_call_limit_async():
    """Test that per tool call limits work with async."""
    yfinance_tools = YFinanceTools(cache_results=True)

    for tool in yfinance_tools.functions.values():
        if tool.name == "get_current_stock_price":
            tool.call_limit = 1
            break

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[yfinance_tools],
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("Find me the current price of TSLA and APPL.")

    # Verify that get_current_stock_price was only called once due to per_tool_call_limit
    stock_price_calls = [t for t in response.tools if t.tool_name == "get_current_stock_price"]
    assert len(stock_price_calls) == 1
    assert stock_price_calls[0].tool_args == {"symbol": "TSLA"}
    assert stock_price_calls[0].result is not None
    assert response.content is not None


@pytest.mark.asyncio
async def test_per_tool_call_limit_stream_async():
    yfinance_tools = YFinanceTools(cache_results=True)

    for tool in yfinance_tools.functions.values():
        if tool.name == "get_current_stock_price":
            tool.call_limit = 1
            break

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[yfinance_tools],
        markdown=True,
        telemetry=False,
    )

    tools = []
    async for chunk in agent.arun("Find me the current price of TSLA and APPL.", stream=True, stream_events=True):
        if chunk.event == RunEvent.tool_call_completed:
            tools.append(chunk.tool)

    stock_price_calls = [t for t in tools if t.tool_name == "get_current_stock_price"]
    assert len(stock_price_calls) == 1, f"Expected 1 stock price call, got {len(stock_price_calls)}"
    assert stock_price_calls[0].tool_args == {"symbol": "TSLA"}
    assert stock_price_calls[0].result is not None


def test_multiple_tools_different_call_limits():
    """Test that different tools can have different call limits and don't interfere with each other."""
    yfinance_tools = YFinanceTools(cache_results=True)

    for tool in yfinance_tools.functions.values():
        if tool.name == "get_current_stock_price":
            tool.call_limit = 1
        elif tool.name == "get_company_info":
            tool.call_limit = 1

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[yfinance_tools],
        markdown=True,
        telemetry=False,
    )
    # This should normally call get_current_stock_price twice and get_company_info twice,
    response = agent.run(
        "First, get the current stock prices for TSLA and AAPL. After getting the results, get the company info for AAPL and GOOGL."
    )

    stock_price_calls = [t for t in (response.tools or []) if t.tool_name == "get_current_stock_price"]
    assert len(stock_price_calls) == 1, f"Expected 1 get_current_stock_price call, got {len(stock_price_calls)}"

    stock_info_calls = [t for t in (response.tools or []) if t.tool_name == "get_company_info"]
    assert len(stock_info_calls) == 1, f"Expected 1 get_company_info calls, got {len(stock_info_calls)}"

    assert response.content is not None


# Tests for search_knowledge_call_limit


@pytest_asyncio.fixture
async def loaded_knowledge_base():
    """Create a knowledge base with sample content."""
    knowledge = Knowledge(
        vector_db=LanceDb(
            table_name="recipes",
            uri="tmp/lancedb",
            search_type=SearchType.vector,
            embedder=OpenAIEmbedder(),
        ),
    )
    await knowledge.add_content_async(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
    )
    return knowledge


def test_search_knowledge_call_limit(loaded_knowledge_base):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        knowledge=loaded_knowledge_base,
        search_knowledge=True,
        search_knowledge_call_limit=1,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Search for one recipe at a time, three times in total, and tell me what you find.")

    # Verify search_knowledge_base was called only once instead of three times
    search_calls = [t for t in (response.tools or []) if t.tool_name == "search_knowledge_base"]
    assert len(search_calls) == 1, f"Expected 1 search_knowledge_base call, got {len(search_calls)}"
    assert search_calls[0].result is not None
    assert response.content is not None


@pytest.mark.asyncio
async def test_search_knowledge_call_limit_async(loaded_knowledge_base):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        knowledge=loaded_knowledge_base,
        search_knowledge=True,
        search_knowledge_call_limit=1,
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("Search for one recipe at a time, three times in total, and tell me what you find.")

    # Verify search_knowledge_base was called only once instead of three times
    search_calls = [t for t in (response.tools or []) if t.tool_name == "search_knowledge_base"]
    assert len(search_calls) == 1, f"Expected 1 search_knowledge_base call, got {len(search_calls)}"
    assert search_calls[0].result is not None
    assert response.content is not None
