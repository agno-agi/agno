import logging
from types import SimpleNamespace
from typing import List

import anthropic
import httpx
import openai
import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from openai.types.chat import ChatCompletion

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.message import Message
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.run.base import RunStatus


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def logged():
    """Agno's logger sets propagate=False, so caplog never sees these; attach a handler directly."""
    logger = logging.getLogger("agno")
    handler = _Collect()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler.records
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def _levels(records: List[logging.LogRecord], text: str) -> List[int]:
    return [r.levelno for r in records if text in r.getMessage()]


def _errors(records: List[logging.LogRecord]) -> List[str]:
    return [r.getMessage() for r in records if r.levelno >= logging.ERROR]


def _openai_error(status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status, request=request, json={"error": {"message": f"status {status}"}})
    error_class = {400: openai.BadRequestError, 429: openai.RateLimitError, 503: openai.InternalServerError}[status]
    return error_class(f"Error code: {status}", response=response, body={"message": f"status {status}"})


def _gemini_error(status: int) -> genai_errors.APIError:
    body = {"error": {"code": status, "message": f"status {status}", "status": "UNAVAILABLE"}}
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent")
    error_class = genai_errors.ServerError if status >= 500 else genai_errors.ClientError
    return error_class(status, body, httpx.Response(status, request=request, json=body))


def _raise(error: Exception):
    def call(**kwargs):
        raise error

    return call


def _messages() -> dict:
    return {"messages": [Message(role="user", content="hi")], "assistant_message": Message(role="assistant")}


def _openai_chat(error: Exception, retries: int) -> OpenAIChat:
    model = OpenAIChat(id="gpt-test", api_key="offline", retries=retries)
    model.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_raise(error))), is_closed=lambda: False
    )
    return model


def _openai_responses(error: Exception, retries: int) -> OpenAIResponses:
    model = OpenAIResponses(id="gpt-test", api_key="offline", retries=retries)
    model.client = SimpleNamespace(responses=SimpleNamespace(create=_raise(error)), is_closed=lambda: False)
    return model


def _gemini(error: Exception, retries: int) -> Gemini:
    model = Gemini(id="gemini-test", api_key="offline", retries=retries)
    model.client = SimpleNamespace(models=SimpleNamespace(generate_content=_raise(error)))
    return model


@pytest.mark.parametrize(
    "build, error, retries, text",
    [
        (_openai_chat, _openai_error(503), 2, "API status error from OpenAI API"),
        (_openai_chat, _openai_error(503), 0, "API status error from OpenAI API"),
        (_openai_chat, _openai_error(429), 2, "Rate limit error from OpenAI API"),
        (_openai_chat, _openai_error(400), 2, "API status error from OpenAI API"),
        (_openai_responses, _openai_error(503), 2, "API status error from OpenAI API"),
        (_openai_responses, _openai_error(400), 2, "API status error from OpenAI API"),
        (_gemini, _gemini_error(503), 2, "Error from Gemini API"),
        (_gemini, _gemini_error(503), 0, "Error from Gemini API"),
        (_gemini, _gemini_error(400), 2, "Error from Gemini API"),
    ],
    ids=[
        "chat-503",
        "chat-503-no-retries",
        "chat-429",
        "chat-400",
        "responses-503",
        "responses-400",
        "gemini-503",
        "gemini-503-no-retries",
        "gemini-400",
    ],
)
def test_an_adapter_logs_the_error_it_raises_at_warning(logged, build, error, retries, text):
    with pytest.raises(ModelProviderError):
        build(error, retries=retries).invoke(**_messages())

    assert _levels(logged, text) == [logging.WARNING]


def _claude(error: Exception) -> Claude:
    model = Claude(id="claude-test", api_key="offline", retries=2, delay_between_retries=0)
    model.client = SimpleNamespace(messages=SimpleNamespace(create=_raise(error)), is_closed=lambda: False)
    return model


def _claude_error(status: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request, json={"type": "error", "error": {"message": f"status {status}"}})
    return anthropic.BadRequestError(f"Error code: {status}", response=response, body=None)


@pytest.mark.parametrize(
    "model",
    [
        lambda: _openai_chat(_openai_error(400), retries=2),
        lambda: _gemini(_gemini_error(503), retries=1),
        lambda: _claude(_claude_error(400)),
    ],
    ids=["openai-400", "gemini-503-after-retries", "claude-400"],
)
def test_a_failed_agent_run_logs_one_error(logged, model):
    run = Agent(model=model()).run("hi")

    assert run.status == RunStatus.error
    [error] = _errors(logged)
    assert error.startswith("Error in Agent run:")


class _FlakyGeminiModels:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_content(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise _gemini_error(503)
        return genai_types.GenerateContentResponse(
            candidates=[
                genai_types.Candidate(
                    content=genai_types.Content(role="model", parts=[genai_types.Part(text="ok")]),
                    finish_reason=genai_types.FinishReason.STOP,
                )
            ],
            usage_metadata=genai_types.GenerateContentResponseUsageMetadata(
                prompt_token_count=3, candidates_token_count=1, total_token_count=4
            ),
        )


class _FlakyChatCompletions:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise _openai_error(503)
        return ChatCompletion.model_validate(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-test",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            }
        )


async def test_a_gemini_call_that_succeeds_on_retry_logs_no_error(logged):
    model = Gemini(id="gemini-test", api_key="offline", retries=1, delay_between_retries=0)
    model.client = SimpleNamespace(aio=SimpleNamespace(models=_FlakyGeminiModels()))

    response = await model.aresponse(messages=[Message(role="user", content="hi")])

    assert response.content == "ok"
    assert _errors(logged) == []


async def test_an_openai_call_that_succeeds_on_retry_logs_no_error(logged):
    model = OpenAIChat(id="gpt-test", api_key="offline", retries=1, delay_between_retries=0)
    model.async_client = SimpleNamespace(
        chat=SimpleNamespace(completions=_FlakyChatCompletions()), is_closed=lambda: False
    )

    response = await model.aresponse(messages=[Message(role="user", content="hi")])

    assert response.content == "ok"
    assert _errors(logged) == []
