import logging
from types import SimpleNamespace
from typing import List

import httpx
import openai
import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from openai.types.chat import ChatCompletion

from agno.exceptions import ModelProviderError
from agno.models.google import Gemini
from agno.models.message import Message
from agno.models.openai import OpenAIChat, OpenAIResponses


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
    "status, retries, expected",
    [
        (503, 2, logging.WARNING),
        (429, 2, logging.WARNING),
        (503, 0, logging.ERROR),
        (400, 2, logging.ERROR),
    ],
)
def test_log_provider_error_follows_the_retry_decision(logged, status, retries, expected):
    OpenAIChat(id="gpt-test", api_key="offline", retries=retries)._log_provider_error(f"boom {status}", status)

    assert _levels(logged, f"boom {status}") == [expected]


def test_log_provider_error_treats_a_context_window_message_as_final(logged):
    model = OpenAIChat(id="gpt-test", api_key="offline", retries=2)

    model._log_provider_error("This model's maximum context length is 8192 tokens", 500)

    assert _levels(logged, "maximum context length") == [logging.ERROR]


@pytest.mark.parametrize(
    "build, error, text",
    [
        (_openai_chat, _openai_error(503), "API status error from OpenAI API"),
        (_openai_chat, _openai_error(429), "Rate limit error from OpenAI API"),
        (_openai_responses, _openai_error(503), "API status error from OpenAI API"),
        (_gemini, _gemini_error(503), "Error from Gemini API"),
    ],
    ids=["chat-503", "chat-429", "responses-503", "gemini-503"],
)
def test_a_retryable_error_is_a_warning_while_retries_remain(logged, build, error, text):
    with pytest.raises(ModelProviderError):
        build(error, retries=2).invoke(**_messages())

    assert _levels(logged, text) == [logging.WARNING]


@pytest.mark.parametrize(
    "build, error, retries, text",
    [
        (_openai_chat, _openai_error(503), 0, "API status error from OpenAI API"),
        (_openai_chat, _openai_error(400), 2, "API status error from OpenAI API"),
        (_openai_responses, _openai_error(400), 2, "API status error from OpenAI API"),
        (_gemini, _gemini_error(503), 0, "Error from Gemini API"),
        (_gemini, _gemini_error(400), 2, "Error from Gemini API"),
    ],
    ids=["chat-503-no-retries", "chat-400", "responses-400", "gemini-503-no-retries", "gemini-400"],
)
def test_an_error_that_will_not_be_retried_stays_an_error(logged, build, error, retries, text):
    with pytest.raises(ModelProviderError):
        build(error, retries=retries).invoke(**_messages())

    assert _levels(logged, text) == [logging.ERROR]


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
