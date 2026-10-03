import pytest

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.togetherlink import TogetherLink
from agno.run.base import RunStatus

MODEL_ID = "zai-org/GLM-5.3-Flash"


def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: Name of the city.
    """
    return f"It is 22 degrees Celsius and sunny in {city}."


def get_stock_price(symbol: str) -> str:
    """Get the latest stock price for a ticker symbol.

    Args:
        symbol: Stock ticker symbol, e.g. AAPL.
    """
    return f"{symbol.upper()} is trading at 123.45 USD."


def flaky_lookup(key: str) -> str:
    """Look up a value by key in the internal registry.

    Args:
        key: The key to look up.
    """
    raise RuntimeError("registry backend is unavailable")


async def aget_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: Name of the city.
    """
    return f"It is 22 degrees Celsius and sunny in {city}."


def _tool_names(response):
    return [t.tool_name for t in (response.tools or [])]


def test_single_tool_call():
    agent = Agent(model=TogetherLink(id=MODEL_ID), tools=[get_weather], telemetry=False)

    response = agent.run("What is the weather in Paris?")

    assert response.status == RunStatus.completed
    assert "get_weather" in _tool_names(response)
    assert "22" in (response.content or "")


@pytest.mark.parametrize(
    "model_id", ["auto", "moonshotai/Kimi-K3", "zai-org/GLM-5.3", "deepseek-ai/DeepSeek-V4.1-Flash"]
)
def test_tool_call_across_models(model_id):
    agent = Agent(model=TogetherLink(id=model_id), tools=[get_weather], telemetry=False)

    response = agent.run("Use the tool to get the weather in Oslo.")

    assert response.status == RunStatus.completed
    assert "get_weather" in _tool_names(response)


def test_multiple_tools_in_one_turn():
    agent = Agent(model=TogetherLink(id=MODEL_ID), tools=[get_weather, get_stock_price], telemetry=False)

    response = agent.run("Get the weather in Tokyo and the stock price of NVDA. Use the tools for both.")

    names = _tool_names(response)
    assert response.status == RunStatus.completed
    assert "get_weather" in names
    assert "get_stock_price" in names
    assert "123.45" in (response.content or "")


def test_parallel_calls_to_same_tool():
    agent = Agent(model=TogetherLink(id=MODEL_ID), tools=[get_weather], telemetry=False)

    response = agent.run("Get the weather for Paris, Berlin and Rome. Call the tool once per city.")

    cities = {t.tool_args.get("city", "").lower() for t in response.tools or []}
    assert {"paris", "berlin", "rome"} <= cities


def test_tool_call_stream():
    agent = Agent(model=TogetherLink(id=MODEL_ID), tools=[get_weather], telemetry=False)

    events = list(agent.run("What is the weather in Lima?", stream=True, yield_run_output=True))
    content = "".join(e.content for e in events[:-1] if isinstance(e.content, str))

    assert "22" in content
    assert "get_weather" in _tool_names(events[-1])


@pytest.mark.asyncio
async def test_async_tool_call_stream():
    agent = Agent(model=TogetherLink(id=MODEL_ID), tools=[aget_weather], telemetry=False)

    chunks = [
        c.content async for c in agent.arun("What is the weather in Cairo?", stream=True) if isinstance(c.content, str)
    ]

    assert "22" in "".join(chunks)


def test_tool_exception_is_recoverable():
    agent = Agent(model=TogetherLink(id=MODEL_ID), tools=[flaky_lookup], telemetry=False)

    response = agent.run("Look up the key 'alpha' using the tool and tell me what happened.")

    assert response.status == RunStatus.completed
    assert "flaky_lookup" in _tool_names(response)
    assert response.content


def test_tool_call_limit_is_respected():
    agent = Agent(model=TogetherLink(id=MODEL_ID), tools=[get_weather], tool_call_limit=1, telemetry=False)

    response = agent.run("Get the weather in Paris, then Berlin, then Rome, one tool call at a time.")

    assert response.status == RunStatus.completed
    executed = [t for t in response.tools or [] if t.result is not None and "sunny" in str(t.result)]
    assert len(executed) <= 1


def test_tool_history_replay(tmp_path):
    """Tool call and tool result messages from earlier runs must replay cleanly through the gateway."""
    agent = Agent(
        model=TogetherLink(id=MODEL_ID),
        tools=[get_weather],
        db=SqliteDb(db_file=str(tmp_path / "tools.db")),
        add_history_to_context=True,
        telemetry=False,
    )

    agent.run("What is the weather in Madrid?", session_id="t1")
    response = agent.run("Which city did I just ask about, and what was the temperature?", session_id="t1")

    assert response.status == RunStatus.completed
    assert "madrid" in (response.content or "").lower()
    assert "22" in (response.content or "")
