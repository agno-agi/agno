import json
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Optional, Union

import httpx

from agno.exceptions import ModelAuthenticationError
from agno.metrics import MessageMetrics
from agno.models.decision.base import AnswerType, DecisionModel, _score_answer
from agno.models.decision.types import (
    BinaryQuestion,
    Choice,
    ChoiceAnswer,
    DecisionResult,
    RefusalAnswer,
    Score,
    State,
)

try:
    from openai import (
        APIConnectionError,
        APIStatusError,
        AsyncOpenAI,
        AuthenticationError,
        OpenAI,
        PermissionDeniedError,
    )
except ModuleNotFoundError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class OpenAIDecisions(DecisionModel):
    """OpenAI's Decisions API.

    Attributes:
        id (str): The model id. Defaults to "gpt-6-luna".
        api_key (Optional[str]): The API key. Read from OPENAI_API_KEY when not set.
        organization (Optional[str]): The OpenAI organization.
        max_retries (Optional[int]): Retries performed by the OpenAI client itself.
    """

    id: str = "gpt-6-luna"
    name: str = "OpenAIDecisions"
    provider: Optional[str] = "OpenAI"

    organization: Optional[str] = None
    max_retries: Optional[int] = None
    default_query: Optional[Dict[str, Any]] = None

    api_key_env: ClassVar[Optional[str]] = "OPENAI_API_KEY"

    def _get_client_params(self) -> Dict[str, Any]:
        base_params = {
            "api_key": self._get_api_key(),
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }
        client_params = {k: v for k, v in base_params.items() if v is not None}
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> OpenAI:  # type: ignore[override]
        if self.client is not None and not self.client.is_closed():
            return self.client
        client_params = self._get_client_params()
        if isinstance(self.http_client, httpx.Client):
            client_params["http_client"] = self.http_client
        self.client = _require_decisions(OpenAI(**client_params))
        return self.client

    def get_async_client(self) -> AsyncOpenAI:  # type: ignore[override]
        if self.async_client is not None and not self.async_client.is_closed():
            return self.async_client
        client_params = self._get_client_params()
        if isinstance(self.http_client, httpx.AsyncClient):
            client_params["http_client"] = self.http_client
        self.async_client = _require_decisions(AsyncOpenAI(**client_params))
        return self.async_client

    def _build_request(
        self, state: State, questions: Dict[str, Union[BinaryQuestion, Choice, Score]]
    ) -> Dict[str, Any]:
        return {
            "model": self.id,
            "input": _state_to_input(state),
            "questions": [self._question_to_openai(name, q) for name, q in questions.items()],
        }

    def _question_to_openai(self, name: str, question: Union[BinaryQuestion, Choice, Score]) -> Dict[str, Any]:
        if isinstance(question, BinaryQuestion):
            instructions = question.instructions
            if question.yes is not None and question.no is not None:
                instructions = f"{instructions}\nYes means: {question.yes}\nNo means: {question.no}"
            return {"type": "predicate", "name": name, "instructions": instructions}
        if isinstance(question, Choice):
            return {
                "type": "choice",
                "name": name,
                "instructions": question.instructions,
                "choices": [_described("value", value, desc) for value, desc in (question.options or {}).items()],
            }
        return {
            "type": "score",
            "name": name,
            "instructions": question.instructions,
            "levels": [_described("label", label, desc) for label, desc in (question.levels or {}).items()],
        }

    def _parse_response(
        self, raw: Dict[str, Any], questions: Dict[str, Union[BinaryQuestion, Choice, Score]]
    ) -> DecisionResult:
        by_name = {a.get("name"): a for a in raw.get("answers") or []}
        answers: Dict[str, AnswerType] = {}
        for name, question in questions.items():
            answer = by_name.get(name)
            if answer is None:
                raise self._provider_error(f"Response has no answer for question '{name}'")
            answers[name] = self._parse_openai_answer(name, question, answer)
        return DecisionResult(answers=answers, model=raw.get("model"), metrics=self._openai_usage(raw.get("usage")))

    def _parse_openai_answer(
        self, name: str, question: Union[BinaryQuestion, Choice, Score], answer: Dict[str, Any]
    ) -> AnswerType:
        if answer.get("type") == "refusal":
            return RefusalAnswer()
        try:
            if isinstance(question, BinaryQuestion):
                probability = float(answer["probability"])
                return question.answer(probability)
            if isinstance(question, Choice):
                return ChoiceAnswer(
                    value=str(answer["choice"]),
                    probabilities={str(p["value"]): float(p["probability"]) for p in answer["probabilities"]},
                    confidence=answer.get("confidence"),
                )
            labels = list(question.levels or {})
            by_index = {int(p["value"]): float(p["probability"]) for p in answer["probabilities"]}
            probabilities = [by_index.get(i, 0.0) for i in range(len(labels))]
            return _score_answer(labels, probabilities, float(answer["score"]), answer.get("confidence"))
        except (KeyError, TypeError, ValueError) as e:
            raise self._provider_error(f"Malformed answer for question '{name}': {answer}") from e

    def _openai_usage(self, usage: Optional[Dict[str, Any]]) -> MessageMetrics:
        metrics = self._usage_to_metrics(usage)
        if usage:
            input_details = usage.get("input_tokens_details") or {}
            metrics.cache_read_tokens = input_details.get("cached_tokens") or 0
            metrics.cache_write_tokens = input_details.get("cache_write_tokens") or 0
            output_details = usage.get("output_tokens_details") or {}
            metrics.reasoning_tokens = output_details.get("reasoning_tokens") or 0
        return metrics

    def _request(self, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self.get_client().decisions.create(**body).model_dump()
        except (AuthenticationError, PermissionDeniedError) as e:
            raise ModelAuthenticationError(
                message=_openai_message(e), status_code=e.status_code, model_name=self.name
            ) from e
        except APIStatusError as e:
            raise self._provider_error(_openai_message(e), status_code=e.status_code) from e
        except APIConnectionError as e:
            raise self._provider_error(str(e)) from e

    async def _arequest(self, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = await self.get_async_client().decisions.create(**body)
            return response.model_dump()
        except (AuthenticationError, PermissionDeniedError) as e:
            raise ModelAuthenticationError(
                message=_openai_message(e), status_code=e.status_code, model_name=self.name
            ) from e
        except APIStatusError as e:
            raise self._provider_error(_openai_message(e), status_code=e.status_code) from e
        except APIConnectionError as e:
            raise self._provider_error(str(e)) from e


def _require_decisions(client: Any) -> Any:
    if not hasattr(client, "decisions"):
        raise ImportError(
            "OpenAIDecisions needs `openai>=3.26.0`, the first release with the Decisions API. "
            "Please upgrade using `pip install --upgrade openai`"
        )
    return client


def _state_to_input(state: State) -> Union[str, List[Dict[str, Any]]]:
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        return json.dumps(state, indent=2, default=str)
    return [{"role": "user", "content": [{"type": "input_text", "text": part} for part in state]}]


def _described(key: str, value: str, description: Optional[str]) -> Dict[str, str]:
    entry = {key: value}
    if description:
        entry["description"] = description
    return entry


def _openai_message(error: APIStatusError) -> str:
    body = error.body
    if isinstance(body, dict):
        inner = body.get("error", body)
        if isinstance(inner, dict) and inner.get("message"):
            return str(inner["message"])
    return str(error)
