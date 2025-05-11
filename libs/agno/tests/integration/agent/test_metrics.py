from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools


def test_session_metrics():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Hi, my name is John")

    input_tokens = sum(response.metrics.get("input_tokens", []))
    output_tokens = sum(response.metrics.get("output_tokens", []))
    total_tokens = sum(response.metrics.get("total_tokens", []))

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens

    assert agent.session_metrics.input_tokens == input_tokens
    assert agent.session_metrics.output_tokens == output_tokens
    assert agent.session_metrics.total_tokens == total_tokens

    response = agent.run("What is current news in France?")

    input_tokens_list = response.metrics.get("input_tokens", [])
    assert len(input_tokens_list) >= 2  # Should be atleast 2 assistant messages

    input_tokens += sum(response.metrics.get("input_tokens", []))
    output_tokens += sum(response.metrics.get("output_tokens", []))
    total_tokens += sum(response.metrics.get("total_tokens", []))

    assert agent.session_metrics.input_tokens == input_tokens
    assert agent.session_metrics.output_tokens == output_tokens
    assert agent.session_metrics.total_tokens == total_tokens


def test_run_response_metrics():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        show_tool_calls=True,
        markdown=True,
    )

    response1 = agent.run("Hello my name is John")
    response2 = agent.run("I live in New York")

    assert len(response1.metrics.get("input_tokens", [])) == 1
    assert len(response2.metrics.get("input_tokens", [])) == 1

    assert len(response1.metrics.get("output_tokens", [])) == 1
    assert len(response2.metrics.get("output_tokens", [])) == 1

    assert len(response1.metrics.get("total_tokens", [])) == 1
    assert len(response2.metrics.get("total_tokens", [])) == 1
