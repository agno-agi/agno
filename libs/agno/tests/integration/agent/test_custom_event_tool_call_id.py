from dataclasses import dataclass


from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import CustomEvent, RunEvent

# This test ensures tool-generated CustomEvent has tool_call_id injected
def test_custom_event_has_tool_call_id_and_matches_tool_call_started():
    @dataclass
    class WeatherRequestEvent(CustomEvent):
        city: str = ""
        temperature: int = 0

    # A simple tool that yields a custom event
    def get_weather(city: str):
        yield WeatherRequestEvent(city=city, temperature=70)

    # Create agent with the tool. Disable telemetry to avoid external calls/side-effects.
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_weather],
        telemetry=False,
    )

    # Stream events so we can capture the ToolCallStarted and the CustomEvent
    response_generator = agent.run("What is the weather in Tokyo?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        events.setdefault(run_response_delta.event, []).append(run_response_delta)

    # Basic expectations
    assert RunEvent.tool_call_started in events
    assert RunEvent.custom_event in events

    # There should be at least one tool_call_started and one custom_event
    tool_started_event = events[RunEvent.tool_call_started][0]
    custom_event = events[RunEvent.custom_event][0]

    # The custom event must have tool_call_id injected
    assert hasattr(custom_event, "tool_call_id"), "CustomEvent should have tool_call_id attribute"
    assert custom_event.tool_call_id is not None, "tool_call_id should not be None"

    # The custom_event.tool_call_id should match the tool_call_started's tool id
    assert hasattr(tool_started_event, "tool") and getattr(tool_started_event, "tool", None) is not None
    assert getattr(tool_started_event.tool, "tool_call_id", None) is not None

    assert custom_event.tool_call_id == tool_started_event.tool.tool_call_id
