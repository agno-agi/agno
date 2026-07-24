"""Unit tests for the A2AClient toolkit (one instance per remote A2A agent)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.a2a import A2AClient, _slug_from_url

AGENT_URL = "http://localhost:9999/a2a/agents/weather-reporter-agent"


def _make_stream_response(kind: str, **fields):
    """Build a mock object that imitates the relevant slice of a2a.types.StreamResponse."""
    msg = MagicMock()
    msg.WhichOneof = lambda field: kind if field == "payload" else None
    for k, v in fields.items():
        setattr(msg, k, v)
    return msg


def _mock_part(text: str):
    p = MagicMock()
    p.WhichOneof = lambda field: "text" if field == "content" else None
    p.text = text
    return p


def _make_terminal_task(state, text: str):
    task = MagicMock()
    task.status.state = state
    history_entry = MagicMock()
    history_entry.parts = [_mock_part(text)]
    task.history = [history_entry]
    return task


def _fake_client(events):
    fake_client = MagicMock()

    async def fake_send(_req):
        for e in events:
            yield e

    fake_client.send_message = fake_send
    fake_client.close = AsyncMock()
    return fake_client


@pytest.fixture
def toolkit():
    return A2AClient(url=AGENT_URL)


async def _send_events_through_toolkit(toolkit, events):
    toolkit._initialized = True
    toolkit._client = _fake_client(events)
    return await toolkit.asend_message(message="hi")


# --- naming / registration (the per-remote-agent factory pattern) --------------------


def test_slug_from_url():
    assert _slug_from_url(AGENT_URL) == "weather_reporter_agent"
    assert _slug_from_url("http://x/a2a/agents/basic_agent/") == "basic_agent"


def test_tool_names_carry_agent_slug(toolkit):
    assert toolkit.name == "a2a_weather_reporter_agent"
    assert set(toolkit.functions.keys()) == {
        "send_message_to_weather_reporter_agent",
        "get_weather_reporter_agent_card",
    }
    assert set(toolkit.async_functions.keys()) == set(toolkit.functions.keys())


def test_two_instances_do_not_collide():
    weather = A2AClient(url=AGENT_URL)
    airbnb = A2AClient(url="http://localhost:7774/a2a/agents/airbnb-search-agent")

    assert weather.name != airbnb.name
    assert not set(weather.functions.keys()) & set(airbnb.functions.keys())


def test_custom_toolkit_name_is_respected():
    tk = A2AClient(url=AGENT_URL, name="weather_tools")
    assert tk.name == "weather_tools"
    # Function names still derive from the URL slug.
    assert "send_message_to_weather_reporter_agent" in tk.functions


def test_url_is_stripped():
    tk = A2AClient(url=AGENT_URL + "/")
    assert tk.url == AGENT_URL


# --- lifecycle -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_resolves_card_and_enriches_descriptions(toolkit):
    fake_card = MagicMock()
    fake_card.name = "Weather Reporter"
    fake_card.description = "Provides weather forecasts."

    with (
        patch("agno.tools.a2a.A2ACardResolver") as mock_resolver_cls,
        patch("agno.tools.a2a.ClientFactory") as mock_factory_cls,
        patch("agno.tools.a2a.httpx.AsyncClient"),
    ):
        mock_resolver_cls.return_value.get_agent_card = AsyncMock(return_value=fake_card)
        mock_factory_cls.return_value.create.return_value = MagicMock()

        await toolkit.connect()

    assert toolkit.initialized
    description = toolkit.functions["send_message_to_weather_reporter_agent"].description
    assert "Weather Reporter" in description
    assert "Provides weather forecasts." in description


@pytest.mark.asyncio
async def test_close_resets_state(toolkit):
    toolkit._initialized = True
    toolkit._client = _fake_client([])
    toolkit._httpx_client = MagicMock(aclose=AsyncMock())

    await toolkit.close()

    assert not toolkit.initialized
    assert toolkit._client is None
    assert toolkit._httpx_client is None


@pytest.mark.asyncio
async def test_asend_message_lazily_connects(toolkit):
    task = _make_terminal_task(__import__("a2a.types", fromlist=["TaskState"]).TaskState.TASK_STATE_COMPLETED, "hello")

    async def fake_connect(force=False):
        toolkit._initialized = True
        toolkit._client = _fake_client([_make_stream_response("task", task=task)])

    with patch.object(toolkit, "connect", side_effect=fake_connect):
        out = await toolkit.asend_message(message="hi")

    assert out == "hello"


# --- message handling --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_asend_message_prefers_final_task(toolkit):
    from a2a.types import TaskState

    artifact = MagicMock(parts=[_mock_part("Hello")])
    task = _make_terminal_task(TaskState.TASK_STATE_COMPLETED, "Hello, world!")
    events = [
        _make_stream_response("artifact_update", artifact_update=MagicMock(artifact=artifact)),
        _make_stream_response("task", task=task),
    ]
    out = await _send_events_through_toolkit(toolkit, events)
    assert out == "Hello, world!"


@pytest.mark.asyncio
async def test_asend_message_falls_back_to_accumulated_chunks(toolkit):
    artifact1 = MagicMock(parts=[_mock_part("Hello")])
    artifact2 = MagicMock(parts=[_mock_part(" world")])
    events = [
        _make_stream_response("artifact_update", artifact_update=MagicMock(artifact=artifact1)),
        _make_stream_response("artifact_update", artifact_update=MagicMock(artifact=artifact2)),
    ]
    out = await _send_events_through_toolkit(toolkit, events)
    assert out == "Hello world"


@pytest.mark.asyncio
async def test_asend_message_empty_input_returns_error(toolkit):
    out = await toolkit.asend_message(message="")
    assert "non-empty" in out.lower()


@pytest.mark.asyncio
async def test_asend_message_wraps_exceptions(toolkit):
    with patch.object(toolkit, "connect", side_effect=RuntimeError("boom")):
        out = await toolkit.asend_message(message="hi")
    assert "Error talking to" in out
    assert "boom" in out


@pytest.mark.asyncio
async def test_asend_message_failed_task_surfaces_error(toolkit):
    from a2a.types import TaskState

    task = _make_terminal_task(TaskState.TASK_STATE_FAILED, "database exploded")
    out = await _send_events_through_toolkit(toolkit, [_make_stream_response("task", task=task)])

    assert out.startswith("Error: remote agent failed")
    assert "database exploded" in out


@pytest.mark.asyncio
async def test_asend_message_cancelled_task_surfaces_error(toolkit):
    from a2a.types import TaskState

    task = _make_terminal_task(TaskState.TASK_STATE_CANCELED, "operator stop")
    out = await _send_events_through_toolkit(toolkit, [_make_stream_response("task", task=task)])

    assert out.startswith("Error: remote agent run was cancelled")
    assert "operator stop" in out


@pytest.mark.asyncio
async def test_asend_message_rejected_task_surfaces_error(toolkit):
    from a2a.types import TaskState

    task = _make_terminal_task(TaskState.TASK_STATE_REJECTED, "not allowed")
    out = await _send_events_through_toolkit(toolkit, [_make_stream_response("task", task=task)])

    assert out.startswith("Error: remote agent rejected the request")
    assert "not allowed" in out


@pytest.mark.asyncio
async def test_asend_message_failed_task_wins_over_accumulated_chunks(toolkit):
    from a2a.types import TaskState

    artifact = MagicMock(parts=[_mock_part("partial answer")])
    task = _make_terminal_task(TaskState.TASK_STATE_FAILED, "boom")
    events = [
        _make_stream_response("artifact_update", artifact_update=MagicMock(artifact=artifact)),
        _make_stream_response("task", task=task),
    ]
    out = await _send_events_through_toolkit(toolkit, events)
    assert out.startswith("Error: remote agent failed")


# --- agent card -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aget_agent_card_returns_cached_card_json(toolkit):
    fake_card = MagicMock()
    toolkit._initialized = True
    toolkit._agent_card = fake_card

    with patch(
        "agno.tools.a2a.json_format.MessageToDict",
        return_value={"name": "Tester", "version": "1.0.0"},
    ):
        out = await toolkit.aget_agent_card()

    parsed = json.loads(out)
    assert parsed["name"] == "Tester"
    assert parsed["version"] == "1.0.0"
