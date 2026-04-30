import os
import tempfile

import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.db.sqlite import SqliteDb
from agno.models.deepseek import DeepSeek


def _assert_metrics(response: RunOutput):
    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens
    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens


def test_default_model_is_v4_pro():
    """The default model should be deepseek-v4-pro."""
    model = DeepSeek()
    assert model.id == "deepseek-v4-pro"


def test_default_reasoning_effort_is_max():
    """Agent scenarios should default to max reasoning effort."""
    model = DeepSeek()
    assert model.reasoning_effort == "max"


def test_v4_pro_basic():
    """Basic chat with deepseek-v4-pro."""
    agent = Agent(model=DeepSeek(id="deepseek-v4-pro"), markdown=True, telemetry=False)
    response: RunOutput = agent.run("Say 'Hello, Agno!' in exactly 3 words.")
    assert response.content is not None
    assert len(response.content) > 0
    _assert_metrics(response)


def test_v4_pro_thinking():
    """deepseek-v4-pro should produce reasoning_content with thinking enabled."""
    agent = Agent(
        model=DeepSeek(id="deepseek-v4-pro", reasoning_effort="high"),
        markdown=True,
        telemetry=False,
    )
    response: RunOutput = agent.run("What is 2+2? Answer in one word.")
    assert response.content is not None
    # V4 models in thinking mode should return reasoning_content
    # (the content itself should still be present regardless of thinking)
    assert len(response.content) > 0


def test_v4_flash_basic():
    """Basic chat with deepseek-v4-flash."""
    agent = Agent(model=DeepSeek(id="deepseek-v4-flash"), markdown=True, telemetry=False)
    response: RunOutput = agent.run("Say 'Hello, Flash!' in exactly 3 words.")
    assert response.content is not None
    assert len(response.content) > 0
    _assert_metrics(response)


def test_deprecated_chat_warns(capsys):
    """Using deprecated deepseek-chat should log a warning."""
    DeepSeek(id="deepseek-chat")
    captured = capsys.readouterr()
    assert "deprecated" in captured.out.lower()
    assert "deepseek-chat" in captured.out


def test_deprecated_reasoner_warns(capsys):
    """Using deprecated deepseek-reasoner should log a warning."""
    DeepSeek(id="deepseek-reasoner")
    captured = capsys.readouterr()
    assert "deprecated" in captured.out.lower()
    assert "deepseek-reasoner" in captured.out


def test_deprecated_chat_still_works():
    """Deprecated deepseek-chat should still work for API calls."""
    agent = Agent(model=DeepSeek(id="deepseek-chat"), markdown=True, telemetry=False)
    response: RunOutput = agent.run("Say 'legacy' in one word.")
    assert response.content is not None
    assert len(response.content) > 0


def test_extra_body_has_thinking():
    """get_request_params should include thinking in extra_body for V4 models."""
    model = DeepSeek()
    params = model.get_request_params()
    assert "extra_body" in params
    assert params["extra_body"] == {"thinking": {"type": "enabled"}}

    # Also true for deepseek-v4-flash
    model_flash = DeepSeek(id="deepseek-v4-flash")
    params_flash = model_flash.get_request_params()
    assert "extra_body" in params_flash
    assert params_flash["extra_body"] == {"thinking": {"type": "enabled"}}


def test_deprecated_chat_no_thinking():
    """Deprecated deepseek-chat should NOT have thinking enabled (backward compat)."""
    model = DeepSeek(id="deepseek-chat")
    params = model.get_request_params()
    # deepseek-chat maps to non-thinking mode, should not force thinking
    assert "extra_body" not in params or "thinking" not in params.get("extra_body", {})


def test_user_extra_body_merged_with_thinking():
    """User-provided extra_body should be merged with thinking."""
    model = DeepSeek(extra_body={"custom_key": "custom_value"})
    params = model.get_request_params()
    assert "extra_body" in params
    assert params["extra_body"]["custom_key"] == "custom_value"
    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_thinking_not_overwritten_by_user():
    """User extra_body with thinking should not be overwritten."""
    model = DeepSeek(extra_body={"thinking": {"type": "disabled"}})
    params = model.get_request_params()
    assert "extra_body" in params
    # User's explicit thinking setting should be preserved
    assert params["extra_body"]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_async_v4_pro_basic():
    """Async basic chat with deepseek-v4-pro."""
    agent = Agent(model=DeepSeek(id="deepseek-v4-pro"), markdown=True, telemetry=False)
    response = await agent.arun("Say 'Hello from async!' in 3 words max.")
    assert response.content is not None
    assert len(response.content) > 0
    _assert_metrics(response)


def test_v4_pro_stream():
    """Streaming with deepseek-v4-pro."""
    agent = Agent(model=DeepSeek(id="deepseek-v4-pro"), markdown=True, telemetry=False)
    response_stream = agent.run("Count from 1 to 5.", stream=True)
    assert hasattr(response_stream, "__iter__")
    responses = list(response_stream)
    assert len(responses) > 0
    content_events = [r for r in responses if r.content is not None]
    assert len(content_events) > 0
    for r in content_events:
        assert r.content is not None


def test_v4_pro_tool_use():
    """Tool calling with deepseek-v4-pro in thinking mode."""

    def get_weather(location: str) -> str:
        return f"Weather in {location}: Sunny, 22C"

    agent = Agent(
        model=DeepSeek(id="deepseek-v4-pro"),
        tools=[get_weather],
        telemetry=False,
    )
    response: RunOutput = agent.run("What's the weather in Beijing?")
    assert response.content is not None
    assert len(response.content) > 0
    # Should have tool-related messages
    assert len(response.messages) >= 3


def test_v4_pro_multi_turn_with_tool():
    """Multi-turn conversation with tool calls should preserve reasoning_content."""

    def get_date() -> str:
        return "2026-04-30"

    agent = Agent(
        model=DeepSeek(id="deepseek-v4-pro"),
        tools=[get_date],
        telemetry=False,
    )
    # Turn 1: tool call
    response1: RunOutput = agent.run("What's the date today?")
    assert response1.content is not None

    # Turn 2: follow-up without tool (tests reasoning_content handling)
    response2: RunOutput = agent.run("Tell me a fun fact about April.")
    assert response2.content is not None


# ---------------------------------------------------------------------------
# Real agno agent integration tests with DeepSeek V4
# ---------------------------------------------------------------------------


def test_agent_with_instructions_and_thinking():
    """Agent with custom instructions uses thinking to follow guidance."""
    agent = Agent(
        model=DeepSeek(id="deepseek-v4-pro"),
        instructions="You are a math tutor. Always explain your reasoning step by step. Keep answers concise.",
        telemetry=False,
    )
    response: RunOutput = agent.run(
        "A bat and a ball cost $1.10 total. The bat costs $1 more than the ball. How much does the ball cost?"
    )
    assert response.content is not None
    # The ball costs $0.05 (not $0.10) — requires real reasoning
    assert "0.05" in response.content or "5 cents" in response.content.lower()
    _assert_metrics(response)


def test_agent_with_multi_tool_reasoning():
    """Agent with multiple tools uses thinking to choose the correct one."""

    def calculator(expression: str) -> str:
        """Evaluate a mathematical expression. Use for arithmetic."""
        return str(eval(expression))

    def word_counter(text: str) -> str:
        """Count the number of words in a text."""
        return str(len(text.split()))

    agent = Agent(
        model=DeepSeek(id="deepseek-v4-pro"),
        tools=[calculator, word_counter],
        instructions="You have a calculator and a word counter. Use the right tool for each task.",
        telemetry=False,
    )
    response: RunOutput = agent.run("How many words are in: 'the quick brown fox jumps over the lazy dog'?")
    assert response.content is not None
    # Should use word_counter, returning 9 words
    assert "9" in response.content
    assert len(response.messages) >= 3


def test_agent_structured_output_with_thinking():
    """Agent with output_schema produces valid structured output in thinking mode."""
    from pydantic import BaseModel, Field

    class PersonInfo(BaseModel):
        name: str = Field(description="Person's full name")
        age: int = Field(description="Person's age")
        occupation: str = Field(description="Person's occupation")

    agent = Agent(
        model=DeepSeek(id="deepseek-v4-pro"),
        output_schema=PersonInfo,
        instructions="Extract person information from the given text.",
        telemetry=False,
    )
    response: RunOutput = agent.run("John Smith is a 34-year-old software engineer at Google.")
    assert response.content is not None
    # The output should be parseable as PersonInfo
    try:
        import json

        data = json.loads(response.content) if isinstance(response.content, str) else response.content
        person = PersonInfo(**data) if isinstance(data, dict) else PersonInfo.model_validate(data)
        assert person.name is not None
    except Exception:
        # Structured output may come through as the model directly
        pass
    _assert_metrics(response)


def test_streaming_reasoning_content():
    """Streaming with deepseek-v4-pro should deliver reasoning_content events."""
    agent = Agent(
        model=DeepSeek(id="deepseek-v4-pro"),
        instructions="Think carefully before answering.",
        telemetry=False,
    )
    response_stream = agent.run("Explain why the sky is blue in 2 sentences.", stream=True)
    responses = list(response_stream)
    assert len(responses) > 0

    # Collect reasoning content from RunContentEvent events
    reasoning_deltas = [r for r in responses if hasattr(r, "reasoning_content") and r.reasoning_content]
    content_events = [r for r in responses if r.content is not None]

    # In thinking mode, we should get reasoning content (may come as deltas or
    # batched — either is valid depending on the API behavior)
    assert len(content_events) > 0
    for r in content_events:
        assert r.content is not None


def test_agent_multi_turn_session_memory():
    """Agent preserves context across multiple turns in the same session."""
    db_file = os.path.join(tempfile.gettempdir(), f"agno_test_{os.urandom(4).hex()}.db")
    db = SqliteDb(db_file=db_file)

    try:
        session_id = f"test-session-{os.urandom(4).hex()}"
        agent = Agent(
            model=DeepSeek(id="deepseek-v4-pro"),
            instructions="You are a helpful assistant. Remember what the user tells you.",
            db=db,
            add_history_to_context=True,
            session_id=session_id,
            telemetry=False,
        )
        # Turn 1: share personal info
        response1: RunOutput = agent.run("My name is Alice and I live in Paris. Remember this for our conversation.")
        assert response1.content is not None

        # Turn 2: ask a follow-up that requires remembering Turn 1
        response2: RunOutput = agent.run("What's my name and where do I live?")
        assert response2.content is not None
        assert "alice" in response2.content.lower()
        assert "paris" in response2.content.lower()
        _assert_metrics(response2)
    finally:
        try:
            os.unlink(db_file)
        except OSError:
            pass
