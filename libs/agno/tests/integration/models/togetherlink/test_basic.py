import asyncio

import pytest

from agno.agent import Agent, RunOutput
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.together import Together
from agno.models.togetherlink import TogetherLink
from agno.run.base import RunStatus

FAST_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
CATALOG_MODELS = [
    "auto",
    "moonshotai/Kimi-K3",
    "zai-org/GLM-5.3",
    "zai-org/GLM-5.3-Flash",
    "deepseek-ai/DeepSeek-V4.1-Flash",
]


def _assert_metrics(response: RunOutput):
    assert response.metrics is not None
    assert response.metrics.input_tokens > 0
    assert response.metrics.output_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens


def test_basic_auto():
    agent = Agent(model=TogetherLink(), telemetry=False)

    response: RunOutput = agent.run("Reply with the single word: pong")

    assert response.status == RunStatus.completed
    assert response.content is not None
    assert "pong" in response.content.lower()
    assert response.model_provider == "TogetherLink"
    assert [m.role for m in response.messages] == ["user", "assistant"]
    _assert_metrics(response)


@pytest.mark.parametrize("model_id", CATALOG_MODELS)
def test_every_catalog_model(model_id):
    agent = Agent(model=TogetherLink(id=model_id), telemetry=False)

    response = agent.run("What is 2 + 2? Reply with just the number.")

    assert response.status == RunStatus.completed
    assert "4" in (response.content or "")
    _assert_metrics(response)


def test_basic_stream_collects_content_and_metrics():
    agent = Agent(model=TogetherLink(id=FAST_MODEL), telemetry=False)

    events = list(agent.run("Count from 1 to 5, comma separated.", stream=True, yield_run_output=True))
    run_output = events[-1]
    chunks = [e.content for e in events[:-1] if isinstance(e.content, str) and e.content]

    assert len(chunks) > 1
    assert "5" in "".join(chunks)
    assert isinstance(run_output, RunOutput)
    _assert_metrics(run_output)


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(model=TogetherLink(id=FAST_MODEL), telemetry=False)

    response = await agent.arun("Reply with the single word: pong")

    assert response.status == RunStatus.completed
    assert "pong" in (response.content or "").lower()
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_stream():
    agent = Agent(model=TogetherLink(id=FAST_MODEL), telemetry=False)

    chunks = [c.content async for c in agent.arun("Count from 1 to 5, comma separated.", stream=True) if c.content]

    assert "5" in "".join(chunks)


def test_reasoning_content_is_surfaced():
    agent = Agent(model=TogetherLink(id="zai-org/GLM-5.3-Flash"), telemetry=False)

    response = agent.run("Is 91 a prime number? Answer yes or no.")

    assert response.status == RunStatus.completed
    assert response.reasoning_content
    assert "no" in (response.content or "").lower()


def test_multi_turn_history_with_reasoning(tmp_path):
    """Earlier turns carry reasoning content; replaying them must not break later requests."""
    agent = Agent(
        model=TogetherLink(id="zai-org/GLM-5.3-Flash"),
        db=SqliteDb(db_file=str(tmp_path / "history.db")),
        add_history_to_context=True,
        num_history_runs=3,
        telemetry=False,
    )

    agent.run("My favourite colour is teal. Just acknowledge it.", session_id="s1")
    agent.run("My favourite number is 42. Just acknowledge it.", session_id="s1")
    response = agent.run("What are my favourite colour and number?", session_id="s1")

    assert response.status == RunStatus.completed
    assert "teal" in (response.content or "").lower()
    assert "42" in (response.content or "")


def test_sessions_are_isolated(tmp_path):
    agent = Agent(
        model=TogetherLink(id=FAST_MODEL),
        db=SqliteDb(db_file=str(tmp_path / "isolation.db")),
        add_history_to_context=True,
        telemetry=False,
    )

    agent.run("The secret word is 'marzipan'. Just acknowledge it.", session_id="a")
    response = agent.run("What is the secret word? If you were never told one, reply exactly: UNKNOWN", session_id="b")

    assert "marzipan" not in (response.content or "").lower()


def test_unicode_and_system_instructions():
    agent = Agent(
        model=TogetherLink(id=FAST_MODEL),
        instructions="Always answer in French.",
        telemetry=False,
    )

    response = agent.run("Translate to French: 'good morning' 🌅 — keep the emoji.")

    assert response.status == RunStatus.completed
    assert "bonjour" in (response.content or "").lower()


def test_request_params_pass_through():
    """max_tokens is forwarded; reasoning models may spend the whole budget before answering."""
    agent = Agent(model=TogetherLink(id="zai-org/GLM-5.3-Flash", max_tokens=16, temperature=0.0), telemetry=False)

    response = agent.run("Write a long essay about the ocean.")

    assert response.status == RunStatus.completed
    assert response.metrics.output_tokens <= 16


def test_default_headers_are_accepted():
    agent = Agent(
        model=TogetherLink(id=FAST_MODEL, default_headers={"x-togetherlink-session-id": "agno-integration-test"}),
        telemetry=False,
    )

    response = agent.run("Reply with the single word: pong")

    assert response.status == RunStatus.completed


def test_invalid_api_key_is_reported_not_masked():
    agent = Agent(
        model=TogetherLink(id=FAST_MODEL, api_key="invalid-key"),
        fallback_models=[Together(id=FAST_MODEL, api_key="invalid-key")],
        telemetry=False,
    )

    response = agent.run("Say ok")

    assert response.status == RunStatus.error
    assert "api key" in (response.content or "").lower()


def test_unknown_model_is_reported():
    agent = Agent(model=TogetherLink(id="does-not/exist"), telemetry=False)

    response = agent.run("Say ok")

    assert response.status == RunStatus.error
    assert "invalid model" in (response.content or "").lower()


def test_unreachable_gateway_falls_back_to_together():
    agent = Agent(
        model=TogetherLink(id=FAST_MODEL, base_url="http://127.0.0.1:9/v1", max_retries=0),
        fallback_models=[Together(id=FAST_MODEL)],
        telemetry=False,
    )

    response = agent.run("Reply with the single word: pong")

    assert response.status == RunStatus.completed
    assert "pong" in (response.content or "").lower()


@pytest.mark.asyncio
async def test_async_unreachable_gateway_falls_back_to_together():
    agent = Agent(
        model=TogetherLink(id=FAST_MODEL, base_url="http://127.0.0.1:9/v1", max_retries=0),
        fallback_models=[Together(id=FAST_MODEL)],
        telemetry=False,
    )

    chunks = [c.content async for c in agent.arun("Reply with the single word: pong", stream=True) if c.content]

    assert "pong" in "".join(chunks).lower()


def test_timeout_is_enforced():
    agent = Agent(model=TogetherLink(id="moonshotai/Kimi-K3", timeout=0.01, max_retries=0), telemetry=False)

    response = agent.run("Write a haiku about latency.")

    assert response.status == RunStatus.error


@pytest.mark.asyncio
async def test_concurrent_runs_on_one_agent(tmp_path):
    agent = Agent(
        model=TogetherLink(id=FAST_MODEL),
        db=SqliteDb(db_file=str(tmp_path / "concurrency.db")),
        telemetry=False,
    )

    numbers = list(range(8))
    responses = await asyncio.gather(
        *[agent.arun(f"Reply with only the number {n}.", session_id=f"c{n}") for n in numbers]
    )

    for n, response in zip(numbers, responses):
        assert response.status == RunStatus.completed
        assert str(n) in (response.content or "")
        assert response.session_id == f"c{n}"


def test_serialization_round_trip():
    from agno.models.utils import get_model, get_model_from_dict

    original = TogetherLink(id="moonshotai/Kimi-K3")
    restored = get_model_from_dict(original.to_dict())

    assert isinstance(get_model("togetherlink:zai-org/GLM-5.3"), TogetherLink)

    assert isinstance(restored, TogetherLink)
    assert restored.id == "moonshotai/Kimi-K3"
    assert restored.base_url == "https://gateway.togetherlink.dev/v1"
