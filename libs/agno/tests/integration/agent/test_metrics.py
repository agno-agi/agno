from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from agno.db.base import SessionType


def test_run_response_metrics():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response1 = agent.run("Hello my name is John")
    response2 = agent.run("I live in New York")

    assert response1.metrics.input_tokens >= 1
    assert response2.metrics.input_tokens >= 1

    assert response1.metrics.output_tokens >= 1
    assert response2.metrics.output_tokens >= 1

    assert response1.metrics.total_tokens >= 1
    assert response2.metrics.total_tokens >= 1


def test_session_metrics(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[WebSearchTools(cache_results=True)],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Hi, my name is John")

    total_input_tokens = response.metrics.input_tokens
    total_output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert response.metrics.input_tokens > 0
    assert response.metrics.output_tokens > 0
    assert response.metrics.total_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens

    session_from_db = agent.db.get_session(session_id=agent.session_id, session_type=SessionType.AGENT)
    assert session_from_db.session_data["session_metrics"]["input_tokens"] == total_input_tokens
    assert session_from_db.session_data["session_metrics"]["output_tokens"] == total_output_tokens
    assert session_from_db.session_data["session_metrics"]["total_tokens"] == total_tokens

    response = agent.run("What is current news in France?")

    assert response.metrics.input_tokens > 0
    assert response.metrics.output_tokens > 0
    assert response.metrics.total_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens

    total_input_tokens += response.metrics.input_tokens
    total_output_tokens += response.metrics.output_tokens
    total_tokens += response.metrics.total_tokens

    # Ensure the total session metrics are updated
    session_from_db = agent.db.get_session(session_id=agent.session_id, session_type=SessionType.AGENT)
    assert session_from_db.session_data["session_metrics"]["input_tokens"] == total_input_tokens
    assert session_from_db.session_data["session_metrics"]["output_tokens"] == total_output_tokens
    assert session_from_db.session_data["session_metrics"]["total_tokens"] == total_tokens


def test_session_metrics_with_add_history(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        add_history_to_context=True,
        num_history_runs=3,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Hi, my name is John")

    total_input_tokens = response.metrics.input_tokens
    total_output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert response.metrics.input_tokens > 0
    assert response.metrics.output_tokens > 0
    assert response.metrics.total_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens

    session_from_db = agent.db.get_session(session_id=agent.session_id, session_type=SessionType.AGENT)
    assert session_from_db.session_data["session_metrics"]["input_tokens"] == total_input_tokens
    assert session_from_db.session_data["session_metrics"]["output_tokens"] == total_output_tokens
    assert session_from_db.session_data["session_metrics"]["total_tokens"] == total_tokens

    response = agent.run("What did I just tell you?")

    assert response.metrics.input_tokens > 0
    assert response.metrics.output_tokens > 0
    assert response.metrics.total_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens

    total_input_tokens += response.metrics.input_tokens
    total_output_tokens += response.metrics.output_tokens
    total_tokens += response.metrics.total_tokens

    # Ensure the total session metrics are updated
    session_from_db = agent.db.get_session(session_id=agent.session_id, session_type=SessionType.AGENT)
    assert session_from_db.session_data["session_metrics"]["input_tokens"] == total_input_tokens
    assert session_from_db.session_data["session_metrics"]["output_tokens"] == total_output_tokens
    assert session_from_db.session_data["session_metrics"]["total_tokens"] == total_tokens
