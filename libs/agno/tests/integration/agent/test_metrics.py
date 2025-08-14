from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools


def test_session_metrics():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Hi, my name is John")

    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens

    assert agent.session_metrics is not None
    assert agent.session_metrics.input_tokens == input_tokens
    assert agent.session_metrics.output_tokens == output_tokens
    assert agent.session_metrics.total_tokens == total_tokens

    response = agent.run("What is current news in France?")

    assert response.metrics is not None
    input_tokens += response.metrics.input_tokens
    output_tokens += response.metrics.output_tokens
    total_tokens += response.metrics.total_tokens

    assert agent.session_metrics is not None
    assert agent.session_metrics.input_tokens == input_tokens
    assert agent.session_metrics.output_tokens == output_tokens
    assert agent.session_metrics.total_tokens == total_tokens


def test_run_response_metrics():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response1 = agent.run("Hello my name is John")
    response2 = agent.run("I live in New York")

    assert response1.metrics is not None
    assert response2.metrics is not None
    assert response1.metrics.input_tokens == 1
    assert response2.metrics.input_tokens == 1

    assert response1.metrics.output_tokens == 1
    assert response2.metrics.output_tokens == 1

    assert response1.metrics.total_tokens == 1
    assert response2.metrics.total_tokens == 1


def test_session_metrics_with_add_history():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        add_history_to_context=True,
        num_history_runs=3,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Hi, my name is John")

    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens

    assert agent.session_metrics is not None
    assert agent.session_metrics.input_tokens == input_tokens
    assert agent.session_metrics.output_tokens == output_tokens
    assert agent.session_metrics.total_tokens == total_tokens

    response = agent.run("What did I just tell you?")

    assert response.metrics is not None
    input_tokens += response.metrics.input_tokens
    output_tokens += response.metrics.output_tokens
    total_tokens += response.metrics.total_tokens

    assert agent.session_metrics.input_tokens == input_tokens
    assert agent.session_metrics.output_tokens == output_tokens
    assert agent.session_metrics.total_tokens == total_tokens
