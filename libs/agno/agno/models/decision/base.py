import asyncio
from copy import deepcopy
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from os import getenv
from time import perf_counter, sleep
from typing import Any, Awaitable, Callable, ClassVar, Dict, List, Mapping, Optional, TypeVar, Union

import httpx
from pydantic import TypeAdapter

from agno.exceptions import ModelAuthenticationError, ModelProviderError
from agno.metrics import MessageMetrics
from agno.models.decision.types import (
    BinaryAnswer,
    BinaryQuestion,
    Choice,
    ChoiceAnswer,
    DecisionResult,
    Question,
    RefusalAnswer,
    Score,
    ScoreAnswer,
    State,
)
from agno.utils.log import log_debug, log_warning

T = TypeVar("T")

_question_adapter: TypeAdapter = TypeAdapter(Question)

AnswerType = Union[BinaryAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer]


@dataclass
class DecisionModel:
    """A model that answers typed questions with probabilities instead of generating text.

    Speaks the System One wire format (`state` plus named `questions`) that Jev introduced and
    Perplexity, Cloudflare and SGLang share. Point `base_url` at any compatible server, or use a
    provider subclass. Providers with a different format override the request and response hooks.
    """

    id: str
    name: str = "DecisionModel"
    provider: Optional[str] = None

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    path: str = "/v1/systemone"
    timeout: Optional[float] = 60.0
    default_headers: Optional[Dict[str, str]] = None
    http_client: Optional[Union[httpx.Client, httpx.AsyncClient]] = None
    client_params: Optional[Dict[str, Any]] = None

    retries: int = 0
    delay_between_retries: int = 1
    exponential_backoff: bool = False

    client: Optional[Any] = None
    async_client: Optional[Any] = None

    # Environment variable the API key is read from; None means the key is optional
    api_key_env: ClassVar[Optional[str]] = None

    def __post_init__(self) -> None:
        if self.provider is None and self.name is not None:
            self.provider = f"{self.name} ({self.id})"

    def get_provider(self) -> str:
        return self.provider or self.name or self.__class__.__name__

    def to_dict(self) -> Dict[str, Any]:
        fields_to_include = {"name": self.name, "id": self.id, "provider": self.provider}
        return {k: v for k, v in fields_to_include.items() if v is not None}

    def __deepcopy__(self, memo: Dict[int, Any]) -> "DecisionModel":
        cls = self.__class__
        new_model = cls.__new__(cls)
        memo[id(self)] = new_model
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in ("client", "async_client"):
                setattr(new_model, f.name, None)
            elif f.name == "http_client":
                setattr(new_model, f.name, value)
            else:
                setattr(new_model, f.name, deepcopy(value, memo))
        return new_model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide(self, state: State, questions: Mapping[str, Any]) -> DecisionResult:
        """Answer every question about `state` in one request."""
        validated = self._validate(state, questions)
        body = self._build_request(state, validated)
        log_debug(f"{self.get_provider()} deciding {len(validated)} question(s)")
        start = perf_counter()
        raw = self._with_retry(lambda: self._request(body))
        return self._finish(raw, validated, start)

    async def adecide(self, state: State, questions: Mapping[str, Any]) -> DecisionResult:
        """Answer every question about `state` in one request."""
        validated = self._validate(state, questions)
        body = self._build_request(state, validated)
        log_debug(f"{self.get_provider()} deciding {len(validated)} question(s)")
        start = perf_counter()
        raw = await self._awith_retry(lambda: self._arequest(body))
        return self._finish(raw, validated, start)

    # ------------------------------------------------------------------
    # Wire format hooks
    # ------------------------------------------------------------------

    def _build_request(
        self, state: State, questions: Dict[str, Union[BinaryQuestion, Choice, Score]]
    ) -> Dict[str, Any]:
        return {
            "model": self.id,
            "state": state,
            "questions": {name: self._question_to_wire(q) for name, q in questions.items()},
        }

    def _question_to_wire(self, question: Union[BinaryQuestion, Choice, Score]) -> Dict[str, Any]:
        wire_type = "noul" if isinstance(question, BinaryQuestion) else question.type
        wire: Dict[str, Any] = {"type": wire_type, "instructions": question.instructions}
        if isinstance(question, BinaryQuestion):
            if question.yes is not None and question.no is not None:
                wire["criteria"] = {"true": question.yes, "false": question.no}
        elif isinstance(question, Choice):
            wire["criteria"] = dict(question.options)
        else:
            wire["criteria"] = [
                f"{label}: {description}" if description else label for label, description in question.levels.items()
            ]
        return wire

    def _parse_response(
        self, raw: Dict[str, Any], questions: Dict[str, Union[BinaryQuestion, Choice, Score]]
    ) -> DecisionResult:
        answers_raw = raw.get("answers") or {}
        answers: Dict[str, AnswerType] = {}
        for name, question in questions.items():
            answer = answers_raw.get(name)
            if answer is None:
                raise self._provider_error(f"Response has no answer for question '{name}'")
            answers[name] = self._parse_answer(name, question, answer)
        return DecisionResult(answers=answers, model=raw.get("model"), metrics=self._usage_to_metrics(raw.get("usage")))

    def _parse_answer(
        self, name: str, question: Union[BinaryQuestion, Choice, Score], answer: Dict[str, Any]
    ) -> AnswerType:
        if answer.get("type") == "refusal":
            return RefusalAnswer()
        try:
            if isinstance(question, BinaryQuestion):
                probability = float(answer["noul"])
                return question.answer(probability)
            if isinstance(question, Choice):
                return ChoiceAnswer(
                    value=answer["choice"],
                    probabilities={str(k): float(v) for k, v in answer["probabilities"].items()},
                    confidence=answer.get("confidence"),
                )
            labels = list(question.levels)
            probabilities = [float(answer["probabilities"].get(str(i), 0.0)) for i in range(len(labels))]
            return _score_answer(labels, probabilities, float(answer["score"]), answer.get("confidence"))
        except (KeyError, TypeError, ValueError) as e:
            raise self._provider_error(f"Malformed answer for question '{name}': {answer}") from e

    def _usage_to_metrics(self, usage: Optional[Dict[str, Any]]) -> MessageMetrics:
        metrics = MessageMetrics()
        if usage:
            metrics.input_tokens = usage.get("input_tokens") or 0
            metrics.output_tokens = usage.get("output_tokens") or 0
            metrics.total_tokens = usage.get("total_tokens") or metrics.input_tokens + metrics.output_tokens
        return metrics

    # ------------------------------------------------------------------
    # Transport hooks
    # ------------------------------------------------------------------

    def _request(self, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = self.get_client().post(self._url(), json=body, headers=self._headers(), timeout=self.timeout)
        except httpx.RequestError as e:
            raise self._provider_error(f"Request to {self.get_provider()} failed: {e}") from e
        return self._handle_response(response)

    async def _arequest(self, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = await self.get_async_client().post(
                self._url(), json=body, headers=self._headers(), timeout=self.timeout
            )
        except httpx.RequestError as e:
            raise self._provider_error(f"Request to {self.get_provider()} failed: {e}") from e
        return self._handle_response(response)

    def get_client(self) -> httpx.Client:
        if isinstance(self.http_client, httpx.Client):
            return self.http_client
        if self.client is None or self.client.is_closed:
            self.client = httpx.Client(**(self.client_params or {}))
        return self.client

    def get_async_client(self) -> httpx.AsyncClient:
        if isinstance(self.http_client, httpx.AsyncClient):
            return self.http_client
        if self.async_client is None or self.async_client.is_closed:
            self.async_client = httpx.AsyncClient(**(self.client_params or {}))
        return self.async_client

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_api_key(self) -> Optional[str]:
        if not self.api_key and self.api_key_env:
            self.api_key = getenv(self.api_key_env)
            if not self.api_key:
                raise ModelAuthenticationError(
                    message=f"{self.api_key_env} not set. Please set the {self.api_key_env} environment variable.",
                    model_name=self.name,
                )
        return self.api_key

    def _url(self) -> str:
        if not self.base_url:
            raise ValueError(f"{self.__class__.__name__} needs a `base_url`")
        return f"{self.base_url.rstrip('/')}/{self.path.lstrip('/')}"

    def _headers(self) -> Dict[str, str]:
        headers = dict(self.default_headers or {})
        api_key = self._get_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        request_id = _request_id(response)
        if response.is_success:
            try:
                raw = response.json()
            except ValueError as e:
                raise self._provider_error(f"Response is not JSON: {response.text[:500]}") from e
            if request_id and isinstance(raw, dict):
                # Headers do not survive the JSON body; `_finish` moves this onto the result
                raw["_request_id"] = request_id
            return raw
        message = _error_message(response)
        error: Exception
        if response.status_code in (401, 403):
            error = ModelAuthenticationError(message=message, status_code=response.status_code, model_name=self.name)
        else:
            error = self._provider_error(message, status_code=response.status_code)
        # The id lets a failed request be traced with the provider; retry_after is the wait the
        # provider asked for, which the retry loop prefers over its own delay
        setattr(error, "request_id", request_id)
        setattr(error, "retry_after", _retry_after_seconds(response))
        raise error

    def _provider_error(self, message: str, status_code: int = 502) -> ModelProviderError:
        return ModelProviderError.classify(
            ModelProviderError(message=message, status_code=status_code, model_name=self.name, model_id=self.id)
        )

    def _validate(self, state: State, questions: Mapping[str, Any]) -> Dict[str, Union[BinaryQuestion, Choice, Score]]:
        if not isinstance(state, (str, dict, list)):
            raise TypeError(f"state must be a str, dict or list of str, got {type(state).__name__}")
        if not questions:
            raise ValueError("decide() needs at least one question")
        validated: Dict[str, Union[BinaryQuestion, Choice, Score]] = {}
        for name, question in questions.items():
            if not isinstance(name, str) or not name:
                raise ValueError("Question names must be non-empty strings")
            validated[name] = (
                question
                if isinstance(question, (BinaryQuestion, Choice, Score))
                else _question_adapter.validate_python(question)
            )
        return validated

    def _finish(
        self, raw: Dict[str, Any], questions: Dict[str, Union[BinaryQuestion, Choice, Score]], start: float
    ) -> DecisionResult:
        request_id = raw.pop("_request_id", None) if isinstance(raw, dict) else None
        result = self._parse_response(raw, questions)
        result.raw = raw
        result.request_id = request_id
        if result.metrics is not None:
            result.metrics.duration = perf_counter() - start
        return result

    def _get_retry_delay(self, attempt: int, error: Optional[BaseException] = None) -> float:
        retry_after = getattr(error, "retry_after", None)
        if retry_after is not None:
            return max(float(retry_after), 0.0)
        if self.exponential_backoff:
            return self.delay_between_retries * (2**attempt)
        return self.delay_between_retries

    def _with_retry(self, call: Callable[[], T]) -> T:
        last_error: Optional[ModelProviderError] = None
        for attempt in range(self.retries + 1):
            try:
                return call()
            except ModelProviderError as e:
                last_error = ModelProviderError.classify(e)
                if not ModelProviderError.is_retryable(last_error) or attempt == self.retries:
                    if last_error is e:
                        raise
                    raise last_error from e
                delay = self._get_retry_delay(attempt, e)
                log_warning(f"{self.get_provider()} error (attempt {attempt + 1}): {e}. Retrying in {delay}s")
                sleep(delay)
        raise last_error  # type: ignore[misc]

    async def _awith_retry(self, call: Callable[[], Awaitable[T]]) -> T:
        last_error: Optional[ModelProviderError] = None
        for attempt in range(self.retries + 1):
            try:
                return await call()
            except ModelProviderError as e:
                last_error = ModelProviderError.classify(e)
                if not ModelProviderError.is_retryable(last_error) or attempt == self.retries:
                    if last_error is e:
                        raise
                    raise last_error from e
                delay = self._get_retry_delay(attempt, e)
                log_warning(f"{self.get_provider()} error (attempt {attempt + 1}): {e}. Retrying in {delay}s")
                await asyncio.sleep(delay)
        raise last_error  # type: ignore[misc]


def _score_answer(
    labels: List[str], probabilities: List[float], score: float, confidence: Optional[float]
) -> ScoreAnswer:
    level = max(range(len(labels)), key=lambda i: probabilities[i])
    return ScoreAnswer(
        value=score,
        level=level,
        label=labels[level],
        probabilities=dict(zip(labels, probabilities)),
        confidence=confidence,
    )


def _request_id(response: httpx.Response) -> Optional[str]:
    for header in ("x-request-id", "x-typesafe-request-id", "request-id"):
        value = response.headers.get(header)
        if value:
            return value
    return None


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    """The wait a `Retry-After` header asks for, in seconds: a delay, or an HTTP date."""
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        until = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return max((until - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    error = body.get("error", body) if isinstance(body, dict) else body
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)
