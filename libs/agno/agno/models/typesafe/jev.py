import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, AsyncIterator, Dict, Iterator, List, Literal, Mapping, Optional
from uuid import uuid4

from pydantic import BaseModel
from typesafe_sdk import TypeSafeError

from agno.exceptions import ModelProviderError
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.models.typesafe._client import DecisionResult, JevClient
from agno.models.typesafe._schemas import compile_decisions, json_schema, questions_dict, validate_questions
from agno.models.typesafe._tools import ToolPlan, compile_tools
from agno.tools.function import Function


class JevAbstentionError(ValueError):
    """No member was dispatched because routing confidence was below the configured minimum."""


@dataclass
class Jev(Model):
    """TypeSafe's typed decision model, using the official Python SDK.

    Modes: questions (fixed decisions), route (one Team member), tools (one
    finite function call). Streaming emits one completed decision, then any
    native stream produced by the selected tool/member.
    """

    id: str = "jev-latest"
    name: str = "Jev"
    provider: str = "TypeSafe"
    supports_native_structured_outputs: bool = True
    supports_json_schema_outputs: bool = True
    mode: Literal["questions", "route", "tools"] = "questions"
    questions: Optional[Mapping[str, Any]] = None
    min_confidence: Optional[float] = None
    fallback_member_id: Optional[str] = None
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: Optional[str] = None
    timeout: Optional[float] = None
    client: Any = field(default=None, repr=False)
    async_client: Any = field(default=None, repr=False)
    _sdk: Optional[JevClient] = field(default=None, init=False, repr=False)

    @property
    def requires_explicit_member_models(self) -> bool:
        return True

    @property
    def requires_structured_member_roster(self) -> bool:
        return self.mode == "route"

    def validate_team_configuration(self, team: Any) -> None:
        if self.mode != "route" or team.mode != "route" or team.determine_input_for_members:
            raise ValueError(
                "A Jev Team leader requires Jev(mode='route'), Team(mode='route'), and determine_input_for_members=False"
            )

    def _get_sdk(self) -> JevClient:
        if self._sdk is None:
            self._sdk = JevClient(self.id, self.api_key, self.base_url, self.timeout, self.client, self.async_client)
        return self._sdk

    def _validate(self) -> None:
        if self.mode not in ("questions", "route", "tools"):
            raise ValueError(f"Unknown Jev mode: {self.mode}")
        if self.mode != "questions" and self.questions is not None:
            raise ValueError("Explicit questions are only supported in questions mode")
        if self.min_confidence is not None and not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if self.mode != "route" and (self.min_confidence is not None or self.fallback_member_id is not None):
            raise ValueError("Confidence/fallback policies are only supported in route mode")
        if self.mode != "questions" and self.cache_response:
            raise ValueError(
                "Response caching is supported only in Jev questions mode; dispatches must execute per run"
            )

    @staticmethod
    def _state(messages: List[Message]) -> Any:
        history = []
        instructions = []
        for message in messages:
            if message.images or message.audio or message.videos or message.files:
                raise ValueError("Jev accepts text/JSON only; media input is unsupported")
            content = message.content
            if isinstance(content, list):
                if not all(isinstance(part, dict) and part.get("type") in ("text", "input_text") for part in content):
                    raise ValueError("Jev accepts text content blocks only")
                content = "\n".join(part.get("text", "") for part in content)
            if message.role in ("system", "developer"):
                if content:
                    instructions.append(content)
            else:
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except (ValueError, TypeError):
                        pass
                entry = {"role": message.role, "content": content}
                for key in ("tool_calls", "tool_call_id", "tool_name"):
                    value = getattr(message, key, None)
                    if value is not None:
                        entry[key] = value
                history.append(entry)
        current = next((item["content"] for item in reversed(history) if item["role"] == "user"), None)
        return {"input": current, "messages": history}, instructions

    def _prepare(self, messages: List[Message], response_format: Any, tools: Any, tool_choice: Any) -> Any:
        self._validate()
        state, instructions = self._state(messages)
        if self.mode == "questions":
            if tools:
                raise ValueError("Use Jev(mode='tools') for bounded tool calling")
            schema = compile_decisions(self.questions, response_format)
            plan = None
        else:
            if response_format is not None:
                raise ValueError(
                    "Jev dispatch modes return the selected tool/member result; put output_schema on the member"
                )
            # Resuming an approved/external call must not make another decision.
            last_user = max((i for i, msg in enumerate(messages) if msg.role == "user"), default=-1)
            completed = [msg for msg in messages[last_user + 1 :] if msg.role == "tool"]
            if completed:
                return ModelResponse(role="assistant", content="\n".join(msg.get_content_string() for msg in completed))
            if tool_choice == "none":
                return ModelResponse(role="assistant", content=json.dumps({"tool": None}))
            plan = compile_tools(tools or [], tool_choice, route=self.mode == "route")
            if self.fallback_member_id is not None and self.fallback_member_id not in (plan.route_members or []):
                raise ValueError("fallback_member_id is not in the current member roster")
            schema = plan.schema
        if instructions:
            data = questions_dict(schema.questions)
            for question in data.values():
                question["instructions"] = {"instructions": instructions, "decision": question["instructions"]}
            schema.questions = validate_questions(data)
        return state, schema, plan

    def _response(self, result: DecisionResult, plan: Optional[ToolPlan]) -> ModelResponse:
        usage = result.metadata.get("usage", {})
        usage = {key: value or 0 for key, value in usage.items()}
        response = ModelResponse(
            role="assistant",
            provider_data={"typesafe": result.metadata},
            response_usage=MessageMetrics(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            ),
        )
        if plan is None:
            response.content = json.dumps(result.values, ensure_ascii=False)
            return response
        name: Optional[str]
        if plan.route_members is not None:
            member_id = result.values["select"]
            confidence = result.metadata["answers"]["select"]["confidence"]
            if self.min_confidence is not None and confidence < self.min_confidence:
                if self.fallback_member_id is None:
                    raise JevAbstentionError(
                        f"Jev routing confidence {confidence} is below {self.min_confidence}; no member dispatched"
                    )
                member_id = self.fallback_member_id
            result.metadata["selected_member_id"] = member_id
            # Team's passthrough delegate uses the original captured input, never this placeholder.
            name, arguments = "delegate_task_to_member", {"member_id": member_id, "task": ""}
        else:
            name, arguments = plan.dispatch(result.values)
        if name is None:
            response.content = json.dumps({"tool": None})
        else:
            response.tool_calls = [
                {"id": str(uuid4()), "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
            ]
        return response

    def _provider_error(self, exc: Exception) -> ModelProviderError:
        return ModelProviderError(
            str(exc), status_code=getattr(exc, "status_code", None) or 502, model_name=self.name, model_id=self.id
        )

    def invoke(
        self,
        messages: List[Message],
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> ModelResponse:
        prepared = self._prepare(messages, response_format, tools, tool_choice)
        if isinstance(prepared, ModelResponse):
            return prepared
        state, schema, plan = prepared
        try:
            result = self._get_sdk().evaluate(state, schema)
        except TypeSafeError as exc:
            raise self._provider_error(exc) from exc
        return self._response(result, plan)

    async def ainvoke(
        self,
        messages: List[Message],
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> ModelResponse:
        prepared = self._prepare(messages, response_format, tools, tool_choice)
        if isinstance(prepared, ModelResponse):
            return prepared
        state, schema, plan = prepared
        try:
            result = await self._get_sdk().aevaluate(state, schema)
        except TypeSafeError as exc:
            raise self._provider_error(exc) from exc
        return self._response(result, plan)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield await self.ainvoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response

    def _run_tools(self, tools: Any, kwargs: Dict[str, Any]) -> Any:
        self._validate()
        if self.mode == "questions":
            if tools:
                raise ValueError("Use Jev(mode='tools') for bounded tool calling")
            return tools
        if kwargs.get("tool_call_limit") is not None and kwargs["tool_call_limit"] < 1:
            kwargs["tool_choice"] = "none"
        # Copy flags for this run; preserve entrypoints, approval requirements and context.
        result = []
        for tool in tools or []:
            if isinstance(tool, Function):
                tool = tool.model_copy(deep=True)
                tool.stop_after_tool_call = True
                tool.show_result = True
            result.append(tool)
        return result

    def _parsed(self, response: ModelResponse, response_format: Any) -> ModelResponse:
        if self.mode == "questions" and response_format is not None and response.content is not None:
            if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                response.parsed = response_format.model_validate_json(response.content)
            else:
                response.parsed = json.loads(response.content)
        return response

    def response(
        self,
        messages: List[Message],
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        tool_call_limit: Optional[int] = None,
        *args: Any,
        **kwargs: Any,
    ) -> ModelResponse:
        policy = {"tool_choice": tool_choice, "tool_call_limit": tool_call_limit}
        tools = self._run_tools(tools, policy)
        return self._parsed(
            super().response(messages, response_format, tools, policy["tool_choice"], tool_call_limit, *args, **kwargs),
            response_format,
        )

    async def aresponse(
        self,
        messages: List[Message],
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        tool_call_limit: Optional[int] = None,
        *args: Any,
        **kwargs: Any,
    ) -> ModelResponse:
        policy = {"tool_choice": tool_choice, "tool_call_limit": tool_call_limit}
        tools = self._run_tools(tools, policy)
        return self._parsed(
            await super().aresponse(
                messages, response_format, tools, policy["tool_choice"], tool_call_limit, *args, **kwargs
            ),
            response_format,
        )

    def response_stream(
        self,
        messages: List[Message],
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        tool_call_limit: Optional[int] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Iterator[Any]:
        policy = {"tool_choice": tool_choice, "tool_call_limit": tool_call_limit}
        tools = self._run_tools(tools, policy)
        yield from super().response_stream(
            messages, response_format, tools, policy["tool_choice"], tool_call_limit, *args, **kwargs
        )

    async def aresponse_stream(
        self,
        messages: List[Message],
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        tool_call_limit: Optional[int] = None,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        policy = {"tool_choice": tool_choice, "tool_call_limit": tool_call_limit}
        tools = self._run_tools(tools, policy)
        async for chunk in super().aresponse_stream(
            messages, response_format, tools, policy["tool_choice"], tool_call_limit, *args, **kwargs
        ):
            yield chunk

    def to_dict(self) -> Dict[str, Any]:
        result = {**super().to_dict(), "mode": self.mode}
        if self.questions is not None:
            result["questions"] = questions_dict(self.questions)
        for key in ("min_confidence", "fallback_member_id"):
            if getattr(self, key) is not None:
                result[key] = getattr(self, key)
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Jev":
        return cls(
            **{
                key: data[key]
                for key in ("id", "mode", "questions", "min_confidence", "fallback_member_id")
                if key in data
            }
        )

    def _get_model_cache_key(self, messages: List[Message], stream: bool, **kwargs: Any) -> str:
        schema = kwargs.get("response_format")
        state, instructions = self._state(messages)
        data = {
            "config": self.to_dict(),
            "endpoint": self.base_url,
            "state": state,
            "instructions": instructions,
            "schema": json_schema(schema) if schema else None,
            "stream": stream,
        }
        return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
