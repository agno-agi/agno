import json
from dataclasses import dataclass, field
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.typesafe import (
    DELEGATE_TO_ALL_MEMBERS_TOOL,
    DELEGATE_TO_MEMBER_TOOL,
    ROUTE_QUESTION_ID,
    TASK_MODE_TOOLS,
    JevConfigError,
    SchemaPlan,
    ToolPlan,
    answers_to_dict,
    answers_to_values,
    build_tool_call,
    decode_tool_call,
    has_tool_round,
    lowest_confidence,
    messages_to_state,
    parse_team_prompt,
    request_text,
    resolve_member_id,
    route_question,
    schema_to_questions,
    system_text,
    tool_names,
    tool_results,
    tools_to_questions,
)

try:
    from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeClient
except ImportError:
    raise ImportError(
        "`typesafe-sdk` not installed. Please install using `pip install typesafe-sdk` (requires Python >= 3.10)"
    )

NOT_GENERATIVE = (
    "Jev cannot generate text. Give the agent an output_schema, give Jev `questions`, or use Jev as the leader "
    "of a route or broadcast team. Team members, memory, session summaries, compression, learning, followups "
    "and reasoning each need their own generative model."
)


@dataclass
class _Plan:
    """What one invoke does: either a ready response, or one System One request and how to read it."""

    mode: str
    state: Any = None
    questions: Dict[str, Any] = field(default_factory=dict)
    # Set when the turn needs no API call
    response: Optional[ModelResponse] = None
    schema: Optional[SchemaPlan] = None
    tools: Optional[ToolPlan] = None
    request: str = ""
    fallback_member_id: Optional[str] = None


@dataclass
class Jev(Model):
    """
    Jev, TypeSafe's System One model.

    Jev does not generate text. It reads a state and answers typed questions about it - pick one
    option, rate along levels, or judge a yes/no - and returns calibrated probabilities. It is a
    decision model for teams and workflows, not a chat model:

    - As the leader of a `mode=TeamMode.route` team it picks the member that handles the request.
      The team's description and instructions are its routing guidance.
    - With an `output_schema` it fills the schema: bool, Literal, Enum, IntEnum and List[Literal]
      fields, each asked using the field description.
    - With `questions` it answers raw System One questions and returns the answers as JSON.
    - With tools it calls one tool whose arguments are closed sets (enum, bool, list of enum).

    The raw answers, probabilities and confidence of every run are on
    `run_output.model_provider_data`.

    For more information, see: https://docs.typesafe.ai
    """

    id: str = "jev-latest"
    name: str = "Jev"
    provider: str = "TypeSafe"

    # The output_schema class is passed through as-is and turned into questions
    supports_native_structured_outputs: bool = True

    # -*- Request parameters
    # Raw System One questions, keyed by an id of your choice. Overrides output_schema.
    questions: Optional[Dict[str, Any]] = None
    # A yes/no probability at or above this counts as yes
    threshold: float = 0.5
    # Routing and tool decisions under this confidence are not acted on
    min_confidence: Optional[float] = None
    # Route mode: the member (id or name) that takes requests Jev is not confident about
    fallback_member: Optional[str] = None
    # Send the system message along as context for output_schema, questions and tool decisions
    add_system_message_to_state: bool = True
    request_params: Optional[Dict[str, Any]] = None

    # -*- Client parameters
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: Optional[float] = None
    # Retries made by the TypeSafe client itself. The model-level `retries` multiply on top of these.
    max_retries: Optional[int] = None
    client_params: Optional[Dict[str, Any]] = None
    # -*- Provide the TypeSafe clients manually
    client: Optional[TypeSafeClient] = None
    async_client: Optional[AsyncTypeSafeClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        self.api_key = self.api_key or getenv("TYPESAFE_API_KEY")
        if not self.api_key:
            raise ModelProviderError(
                message="TYPESAFE_API_KEY not set. Please set the TYPESAFE_API_KEY environment variable.",
                status_code=401,
                model_name=self.name,
                model_id=self.id,
            )
        params: Dict[str, Any] = {"api_key": self.api_key, "model": self.id}
        if self.base_url is not None:
            params["base_url"] = self.base_url
        if self.timeout is not None:
            params["timeout"] = self.timeout
        if self.max_retries is not None:
            params["retry"] = RetryPolicy(max_retries=self.max_retries)
        if self.client_params:
            params.update(self.client_params)
        return params

    def get_client(self) -> TypeSafeClient:
        if self.client is None:
            self.client = TypeSafeClient(**self._get_client_params())
        return self.client

    def get_async_client(self) -> AsyncTypeSafeClient:
        if self.async_client is None:
            self.async_client = AsyncTypeSafeClient(**self._get_client_params())
        return self.async_client

    def to_dict(self) -> Dict[str, Any]:
        model_dict = super().to_dict()
        model_dict.update(
            {
                "threshold": self.threshold,
                "min_confidence": self.min_confidence,
                "fallback_member": self.fallback_member,
                "add_system_message_to_state": self.add_system_message_to_state,
            }
        )
        return {k: v for k, v in model_dict.items() if v is not None}

    # -*- Deciding what a turn is

    def _plan(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> _Plan:
        names = set(tool_names(tools))
        leads_team = bool(names & ({DELEGATE_TO_MEMBER_TOOL, DELEGATE_TO_ALL_MEMBERS_TOOL} | TASK_MODE_TOOLS))
        schema = (
            response_format if isinstance(response_format, type) and issubclass(response_format, BaseModel) else None
        )
        # A team leader's prompt is the roster and framework instructions, not context for a judgment
        include_system = self.add_system_message_to_state and not leads_team

        # The turn after a tool ran: judge the results if there is a schema, otherwise hand them back
        if has_tool_round(messages):
            if schema is not None and self.questions is None:
                plan = schema_to_questions(schema, self.threshold)
                return _Plan(
                    mode="schema",
                    state=messages_to_state(messages, include_system=include_system),
                    questions=plan.questions,
                    schema=plan,
                )
            results = "\n\n".join(r["result"] for r in tool_results(messages) if r["result"])
            return _Plan(mode="tool_result", response=ModelResponse(role=self.assistant_message_role, content=results))

        if DELEGATE_TO_ALL_MEMBERS_TOOL in names:
            request = request_text(messages)
            call = build_tool_call(DELEGATE_TO_ALL_MEMBERS_TOOL, {"task": request})
            return _Plan(mode="broadcast", response=ModelResponse(role=self.assistant_message_role, tool_calls=[call]))

        if leads_team:
            return self._plan_route(messages, names)

        if self.questions is not None:
            if schema is not None:
                raise JevConfigError(
                    "Jev was given both `questions` and an output_schema. Use one: `questions` returns the raw "
                    "answers as JSON, an output_schema returns the filled schema."
                )
            if names:
                log_warning("Jev was given `questions`, so its tools are ignored.")
            if not self.questions:
                raise JevConfigError("Jev was given an empty `questions` map.")
            state = messages_to_state(messages, include_system=include_system)
            return _Plan(mode="questions", state=state, questions=dict(self.questions))

        if schema is not None:
            if names:
                log_warning("Jev fills the output_schema in one step, so its tools are ignored.")
            plan = schema_to_questions(schema, self.threshold)
            state = messages_to_state(messages, include_system=include_system)
            return _Plan(mode="schema", state=state, questions=plan.questions, schema=plan)

        if response_format is not None:
            raise JevConfigError(
                "Jev needs the output_schema class itself to build its questions. Pass a pydantic model as "
                "output_schema and leave use_json_mode off."
            )

        if names and tool_choice != "none":
            tool_plan = tools_to_questions(tools or [], tool_choice=tool_choice, threshold=self.threshold)
            state = messages_to_state(messages, include_system=include_system)
            return _Plan(mode="tools", state=state, questions=tool_plan.questions, tools=tool_plan)

        raise JevConfigError(NOT_GENERATIVE)

    def _plan_route(self, messages: List[Message], names: set) -> _Plan:
        prompt = parse_team_prompt(system_text(messages))
        if prompt.mode != "route":
            raise JevConfigError(
                f"Jev can only lead route or broadcast teams, and this team runs in {prompt.mode or 'an unknown'} "
                "mode. Set mode=TeamMode.route: Jev picks the member, and that member's reply is the answer. "
                "Jev cannot write sub-tasks or combine member replies."
            )
        if not prompt.members:
            raise JevConfigError(
                "Jev found no team members in the leader's system message. It reads the roster the Team writes "
                "there, so a custom `system_message` on the team leaves it nothing to choose from."
            )
        other_tools = sorted(names - {DELEGATE_TO_MEMBER_TOOL})
        if other_tools:
            log_debug(f"Jev routes and does nothing else; ignoring leader tools: {', '.join(other_tools)}")

        fallback_member_id = None
        if self.fallback_member is not None:
            fallback_member_id = resolve_member_id(prompt.members, self.fallback_member)
            if fallback_member_id is None:
                known = ", ".join(m.id for m in prompt.members)
                raise JevConfigError(f"fallback_member '{self.fallback_member}' is not on the team. Members: {known}")

        request = request_text(messages)
        if len(prompt.members) == 1:
            call = build_tool_call(DELEGATE_TO_MEMBER_TOOL, {"member_id": prompt.members[0].id, "task": request})
            return _Plan(mode="route", response=ModelResponse(role=self.assistant_message_role, tool_calls=[call]))

        return _Plan(
            mode="route",
            state=messages_to_state(messages, include_system=False),
            questions={ROUTE_QUESTION_ID: route_question(prompt.members, prompt.guidance)},
            request=request,
            fallback_member_id=fallback_member_id,
        )

    # -*- Reading the answers

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        """Turn a System One response into a ModelResponse, according to the plan it answers."""
        plan: _Plan = kwargs["plan"]
        answers = answers_to_dict(getattr(response, "answers", None))
        model_response = ModelResponse(role=self.assistant_message_role)
        selected: Any = None
        confidence = lowest_confidence(answers)

        if plan.mode == "route":
            selected = answers[ROUTE_QUESTION_ID]["choice"]
            if self.min_confidence is not None and confidence is not None and confidence < self.min_confidence:
                reason = f"Jev was not confident enough to route to '{selected}' (confidence {confidence:.2f})."
                selected = self._unsure(reason, plan.fallback_member_id)
            # No content: anything the leader writes is prepended to the member's reply
            model_response.tool_calls = [
                build_tool_call(DELEGATE_TO_MEMBER_TOOL, {"member_id": selected, "task": plan.request})
            ]

        elif plan.mode == "tools" and plan.tools is not None:
            selected, arguments, read = decode_tool_call(answers, plan.tools)
            confidence = lowest_confidence(answers, read)
            if selected is None:
                self._unsure("Jev decided that none of the tools fits the request.", None)
            if self.min_confidence is not None and confidence is not None and confidence < self.min_confidence:
                self._unsure(f"Jev was not confident enough to call '{selected}' (confidence {confidence:.2f}).", None)
            model_response.tool_calls = [build_tool_call(str(selected), arguments)]
            selected = {"tool": selected, "arguments": arguments}

        elif plan.mode == "schema" and plan.schema is not None:
            parsed = plan.schema.model.model_validate(answers_to_values(answers, plan.schema))
            model_response.parsed = parsed
            # The run turns this JSON back into the output_schema
            model_response.content = parsed.model_dump_json()

        else:
            model_response.content = json.dumps(answers)

        usage = getattr(response, "usage", None)
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", None) or 0
            output_tokens = getattr(usage, "output_tokens", None) or 0
            model_response.response_usage = MessageMetrics(
                input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=input_tokens + output_tokens
            )

        model_response.provider_data = {
            "mode": plan.mode,
            "answers": answers,
            "selected": selected,
            "confidence": confidence,
            "model": getattr(response, "model", None),
            "request_id": getattr(response, "request_id", None),
        }
        return model_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        # Jev answers in one piece; the streaming methods yield a complete ModelResponse
        return response

    def _unsure(self, reason: str, fallback_member_id: Optional[str]) -> str:
        """Jev would not act on a decision. Route to the fallback member if there is one; otherwise fail in a
        way the run's `fallback_models` can pick up, since Jev cannot write a reply of its own."""
        if fallback_member_id is not None:
            log_debug(f"{reason} Using fallback member '{fallback_member_id}'")
            return fallback_member_id
        raise ModelProviderError(
            message=(
                f"{reason} Add a generative model to `fallback_models` to handle requests Jev will not decide, "
                "or set `fallback_member` on a route team."
            ),
            status_code=502,
            model_name=self.name,
            model_id=self.id,
        )

    def _error(self, e: Exception) -> ModelProviderError:
        if isinstance(e, ModelProviderError):
            return e
        if isinstance(e, JevConfigError):
            # A setup problem: not retried, and never hidden behind a fallback model
            status_code = 400
        else:
            log_error(f"Unexpected error calling TypeSafe API: {str(e)}")
            sdk_status = getattr(e, "status", None)
            if isinstance(sdk_status, int):
                status_code = sdk_status
            else:
                status_code = 504 if isinstance(e, TimeoutError) else 503 if isinstance(e, ConnectionError) else 502
        return ModelProviderError(message=str(e), status_code=status_code, model_name=self.name, model_id=self.id)

    def _log_request(self, plan: _Plan) -> None:
        log_debug(f"Jev {plan.mode} request with {len(plan.questions)} question(s)")

    # -*- The four invokes

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
        **kwargs: Any,
    ) -> ModelResponse:
        try:
            plan = self._plan(messages, response_format=response_format, tools=tools, tool_choice=tool_choice)
            if plan.response is not None:
                plan.response.provider_data = {"mode": plan.mode}
                return plan.response
            self._log_request(plan)
            assistant_message.metrics.start_timer()
            provider_response = self.get_client().system_one(plan.state, plan.questions, **(self.request_params or {}))
            assistant_message.metrics.stop_timer()
            return self._parse_provider_response(provider_response, plan=plan)
        except Exception as e:
            raise self._error(e) from e

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
        **kwargs: Any,
    ) -> ModelResponse:
        try:
            plan = self._plan(messages, response_format=response_format, tools=tools, tool_choice=tool_choice)
            if plan.response is not None:
                plan.response.provider_data = {"mode": plan.mode}
                return plan.response
            self._log_request(plan)
            assistant_message.metrics.start_timer()
            provider_response = await self.get_async_client().system_one(
                plan.state, plan.questions, **(self.request_params or {})
            )
            assistant_message.metrics.stop_timer()
            return self._parse_provider_response(provider_response, plan=plan)
        except Exception as e:
            raise self._error(e) from e

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
        **kwargs: Any,
    ) -> Iterator[ModelResponse]:
        # Jev has nothing to stream: the whole answer arrives at once, as a single chunk
        try:
            plan = self._plan(messages, response_format=response_format, tools=tools, tool_choice=tool_choice)
            if plan.response is not None:
                plan.response.provider_data = {"mode": plan.mode}
                yield plan.response
                return
            self._log_request(plan)
            provider_response = self.get_client().system_one(plan.state, plan.questions, **(self.request_params or {}))
            yield self._parse_provider_response(provider_response, plan=plan)
        except Exception as e:
            raise self._error(e) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[ModelResponse]:
        try:
            plan = self._plan(messages, response_format=response_format, tools=tools, tool_choice=tool_choice)
            if plan.response is not None:
                plan.response.provider_data = {"mode": plan.mode}
                yield plan.response
                return
            self._log_request(plan)
            provider_response = await self.get_async_client().system_one(
                plan.state, plan.questions, **(self.request_params or {})
            )
            yield self._parse_provider_response(provider_response, plan=plan)
        except Exception as e:
            raise self._error(e) from e
