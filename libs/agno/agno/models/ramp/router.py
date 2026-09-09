from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.metrics import MessageMetrics
from agno.models.message import Message
from agno.models.openai.open_responses import OpenResponses
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.tools.function import Function
from agno.utils.log import log_warning

try:
    from openai.types.responses import Response, ResponseReasoningItem, ResponseStreamEvent, ResponseUsage
except ImportError as e:
    raise ImportError("`openai` not installed. Please install using `pip install openai -U`") from e

# Agno bookkeeping that Function.to_dict() carries but no provider understands. Router forwards
# the tool object to the upstream provider, which validates it.
INTERNAL_TOOL_KEYS = ("requires_confirmation", "external_execution", "approval_type")


@dataclass
class RampRouter(OpenResponses):
    """
    A class for interacting with models through Ramp Router, an OpenAI Responses API gateway.

    Router exposes one `/v1/responses` endpoint in front of several upstream providers (OpenAI,
    Anthropic, Fireworks, xAI). There is no `/v1/chat/completions` endpoint.

    For more information, see: https://docs.router.com

    Attributes:
        id (str): The model id. Defaults to "gpt-5.6-luna". `GET /v1/models` is authoritative
            for which ids a given key can reach; ids are account-scoped.
        name (str): The model name. Defaults to "RampRouter".
        provider (str): The provider name. Defaults to "RampRouter".
        api_key (Optional[str]): The API key. Uses RAMP_ROUTER_API_KEY env var if not set.
        base_url (str): The base URL. Defaults to "https://api.router.com/v1".
        models (Optional[List[str]]): Routing candidates tried in order. Set this instead of
            `id`; sending both is rejected. Entries are the `router.catalog_id` values from
            `GET /v1/models` ("openai:gpt-5-nano"), optionally suffixed with a service tier
            ("openai:gpt-5-nano:flex").
        allow_flex_tier (Optional[bool]): Allow the flex service tier. Only OpenAI and Vertex
            models accept `True`; everything else rejects it, as does any request that routes
            with `models` rather than a single `id`.
        provider_timeout (Optional[float]): Seconds to wait on the upstream provider before
            failing over to the next candidate.
        timeout_before_headers (Optional[float]): Seconds to wait for the upstream provider's
            first response headers.

    Router rejects unknown request parameters rather than ignoring them, and the accepted set
    varies by the model that serves the request: `temperature`/`top_p` are rejected by reasoning
    models, and `reasoning.effort` is rejected by non-reasoning ones. Effort vocabularies are
    per-model and wider than OpenAI's, and `reasoning_effort` takes any of them:
    `RampRouter(reasoning_effort="xhigh")`.

    `background=True` is not supported. Router accepts the request and queues the generation, but
    serves no endpoint to read it back, so it can never be collected.

    Example:
        ```python
        from agno.agent import Agent
        from agno.models.ramp import RampRouter

        agent = Agent(
            model=RampRouter(id="gpt-5.6-luna"),
            markdown=True,
        )
        agent.print_response("Write a haiku about routing")
        ```
    """

    id: str = "gpt-5.6-luna"
    name: str = "RampRouter"
    provider: str = "RampRouter"

    api_key: Optional[str] = None
    base_url: str = "https://api.router.com/v1"

    # Left unset so Router applies its own storage default. `store=False` additionally switches on
    # the base class's reasoning-item replay, which Router has not been verified to accept, and the
    # models behind Router emit reasoning items on nearly every request.
    store: Optional[bool] = None

    # Router-only request fields, sent via extra_body.
    models: Optional[List[str]] = None
    allow_flex_tier: Optional[bool] = None
    provider_timeout: Optional[float] = None
    timeout_before_headers: Optional[float] = None

    # `_using_reasoning_model()` is deliberately inherited from OpenResponses, which returns False.
    # Router's catalog is full of ids that OpenAIResponses' prefix match would classify as reasoning
    # models, and that branch chains turns with `previous_response_id`. Chaining silently no-ops on
    # the Anthropic and Fireworks backings: HTTP 200, no error, and no memory of the prior turn.
    # Agno replays the full message history instead, which is correct on every backing.

    def __post_init__(self) -> None:
        super().__post_init__()

        if self.background:
            # Router queues and bills the generation, then has nowhere to serve it from: there is
            # no GET /v1/responses/{id}. The base class would poll a 404 until background_max_wait.
            raise ValueError("Router does not support background mode. Set background=False on RampRouter.")

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for RAMP_ROUTER_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.

        Raises:
            ModelAuthenticationError: If RAMP_ROUTER_API_KEY is not set.
        """
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("RAMP_ROUTER_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="RAMP_ROUTER_API_KEY not set. Please set the RAMP_ROUTER_API_KEY environment variable.",
                    model_name=self.name,
                )

        # Define base client params
        base_params: Dict[str, Any] = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)

        return client_params

    def _get_model_request_kwargs(self) -> Dict[str, Any]:
        """Select a single model, or hand Router the candidate list to choose from.

        `model` and `models` are mutually exclusive; sending both is rejected.
        """
        if self.models:
            return {}
        return {"model": self.id}

    def _set_reasoning_request_param(self, base_params: Dict[str, Any]) -> Dict[str, Any]:
        """Only send a `reasoning` block when the caller asked for one.

        The base class sends `reasoning: {}` on every request. Router accepts that, but the block
        is meaningless unset and Router rejects request fields it does not recognize, so there is
        no margin in sending one by default.
        """
        if self.reasoning is None and self.reasoning_effort is None and self.reasoning_summary is None:
            return base_params

        reasoning: Dict[str, Any] = dict(self.reasoning or {})
        if self.reasoning_effort is not None:
            reasoning["effort"] = self.reasoning_effort
        if self.reasoning_summary is not None:
            reasoning["summary"] = self.reasoning_summary

        base_params["reasoning"] = reasoning
        return base_params

    def get_request_params(
        self,
        messages: Optional[List[Message]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests, including the Router-only request fields.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        request_params = super().get_request_params(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )

        # The OpenAI SDK's create() has a closed signature, so Router-only body fields ride in
        # extra_body, which the SDK merges into the request body at the top level.
        router_params: Dict[str, Any] = {
            "allow_flex_tier": self.allow_flex_tier,
            "provider_timeout": self.provider_timeout,
            "timeout_before_headers": self.timeout_before_headers,
        }
        router_params = {k: v for k, v in router_params.items() if v is not None}
        # Gated the same way _get_model_request_kwargs gates it, so an empty candidate list means
        # the same thing in both places. Sending `models: []` alongside `model` is rejected.
        if self.models:
            router_params["models"] = self.models
        if router_params:
            # Copy: the extra_body already in request_params is self.extra_body itself, and
            # mutating it would accumulate across calls.
            extra_body = dict(request_params.get("extra_body") or {})
            extra_body.update(router_params)
            request_params["extra_body"] = extra_body

        return request_params

    def _format_messages(
        self,
        messages: List[Message],
        compress_tool_results: bool = False,
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
    ) -> List[Union[Dict[str, Any], ResponseReasoningItem]]:
        """Format messages for the request, without the ids of earlier function calls.

        A reasoning model emits a reasoning item ahead of the function call it decided on, and
        binds the two by item id. Replaying the call by that id is then rejected unless the
        reasoning item comes with it, which Agno does not carry across turns. `call_id`, which is
        what pairs the call with its output, is unaffected.
        """
        formatted_messages = super()._format_messages(messages, compress_tool_results, tools=tools)

        for message in formatted_messages:
            if isinstance(message, dict) and message.get("type") == "function_call":
                message.pop("id", None)
        return formatted_messages

    def _format_tool_params(
        self, messages: List[Message], tools: Optional[List[Union[Function, Dict[str, Any]]]] = None
    ) -> List[Dict[str, Any]]:
        """Format the tool parameters, dropping the agno-internal keys.

        Router forwards the tool object to the upstream provider, which validates it.
        """
        formatted_tools = super()._format_tool_params(messages=messages, tools=tools)

        cleaned: List[Dict[str, Any]] = []
        for tool in formatted_tools:
            if tool.get("type") == "function" and any(key in tool for key in INTERNAL_TOOL_KEYS):
                # Rebuild rather than pop: the base class hands back the caller's own tool dict.
                tool = {key: value for key, value in tool.items() if key not in INTERNAL_TOOL_KEYS}
            cleaned.append(tool)
        return cleaned

    def _get_metrics(self, response_usage: ResponseUsage) -> MessageMetrics:
        """
        Parse the given usage into an Agno MessageMetrics object.

        The usage envelope differs by the provider that served the request: the Anthropic and
        Fireworks backings omit fields the OpenAI one sends, so every field is coerced to an int
        before it reaches MessageMetrics, which adds them.

        Args:
            response_usage: The usage reported by the provider.

        Returns:
            MessageMetrics: Parsed metrics data
        """
        metrics = MessageMetrics()

        metrics.input_tokens = response_usage.input_tokens or 0
        metrics.output_tokens = response_usage.output_tokens or 0
        metrics.total_tokens = response_usage.total_tokens or 0

        if input_tokens_details := response_usage.input_tokens_details:
            metrics.cache_read_tokens = getattr(input_tokens_details, "cached_tokens", None) or 0
            metrics.cache_write_tokens = getattr(input_tokens_details, "cache_write_tokens", None) or 0

        if output_tokens_details := response_usage.output_tokens_details:
            metrics.reasoning_tokens = getattr(output_tokens_details, "reasoning_tokens", None) or 0

        return metrics

    @staticmethod
    def _has_reasoning_summary(response: Response) -> bool:
        """Whether the response carried a reasoning summary, as the base class counts one."""
        for item in response.output or []:
            if getattr(item, "type", None) != "reasoning":
                continue
            for summary in getattr(item, "summary", None) or []:
                text = summary.get("text") if isinstance(summary, dict) else getattr(summary, "text", None)
                if text:
                    return True
        return False

    def _parse_provider_response(self, response: Response, **kwargs: Any) -> ModelResponse:
        """
        Parse a response into a ModelResponse, without mirroring the answer as reasoning.

        When `reasoning` is set and no summary came back, the base class copies the answer into
        `reasoning_content`. Reaching Router's wider per-model effort values means setting
        `reasoning`, so that heuristic would report every answer twice.
        """
        model_response = super()._parse_provider_response(response, **kwargs)

        if self.reasoning is not None and not self._has_reasoning_summary(response):
            model_response.reasoning_content = None
        return model_response

    def _parse_provider_response_delta(
        self, stream_event: ResponseStreamEvent, assistant_message: Message, tool_use: Dict[str, Any]
    ) -> Tuple[ModelResponse, Dict[str, Any]]:
        """
        Parse a streaming event into a ModelResponse.

        A generation that runs out of `max_output_tokens` terminates on `response.incomplete`
        rather than `response.completed`, which the base class does not read usage from.

        Text deltas are also not mirrored into `reasoning_content`; see `_parse_provider_response`.
        """
        event_type = getattr(stream_event, "type", None)

        if event_type == "response.incomplete":
            model_response = ModelResponse()
            response = getattr(stream_event, "response", None)
            usage = getattr(response, "usage", None)
            if usage is not None:
                model_response.response_usage = self._get_metrics(usage)
            log_warning("Router stopped the response before it was complete.")
            return model_response, tool_use

        model_response, tool_use = super()._parse_provider_response_delta(stream_event, assistant_message, tool_use)

        if event_type == "response.output_text.delta":
            model_response.reasoning_content = None
        return model_response, tool_use

    def count_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        output_schema: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        """Count tokens locally.

        The base class counts them through an OpenAI platform endpoint that Router does not serve,
        which costs a doomed round-trip on every compression check.
        """
        from agno.models.base import Model

        return Model.count_tokens(self, messages, tools, output_schema)

    async def acount_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        output_schema: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        """Async version of count_tokens."""
        from agno.models.base import Model

        return await Model.acount_tokens(self, messages, tools, output_schema)
