from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput


@dataclass
class MoonShot(OpenAILike):
    """
    A class for interacting with MoonShot (Kimi) models.

    Reasoning is exposed through two parameters. Which one a given model honours depends
    on its generation; parameters that do not apply are ignored by the API.

    - ``reasoning_effort``: top-level parameter controlling how much the model thinks.
      Used by Kimi K3, which accepts "low", "high" and "max", and defaults to "max" when
      the parameter is omitted. "max" can spend a long time reasoning even on simple
      prompts, so drop to "low" when latency matters more than depth. See:
      https://platform.kimi.ai/docs/guide/use-thinking-effort
    - ``use_thinking``: toggles thinking via the nested ``thinking`` object. Used by the
      Kimi K2.x line, which reasons by default; set it to False for faster, cheaper
      responses. See:
      https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model

    Models return their reasoning in ``reasoning_content``, which is parsed automatically
    and fed back into the conversation on subsequent turns.

    Kimi supports both output modes behind ``output_schema``: native structured output
    (``response_format={"type": "json_schema"}``, used by default) and JSON mode
    (``response_format={"type": "json_object"}``, via ``use_json_mode=True``). See:
    https://platform.kimi.ai/docs/guide/use-json-mode-feature-of-kimi-api

    Attributes:
        id (str): The model id. Defaults to "kimi-k3".
        name (str): The model name. Defaults to "Moonshot".
        provider (str): The provider name. Defaults to "Moonshot".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.moonshot.ai/v1".
        use_thinking (Optional[bool]): Toggle thinking mode. None uses the model default.
    """

    id: str = "kimi-k3"
    name: str = "Moonshot"
    provider: str = "Moonshot"

    api_key: Optional[str] = field(default_factory=lambda: getenv("MOONSHOT_API_KEY"))
    base_url: str = "https://api.moonshot.ai/v1"

    # Toggle thinking mode via the nested `thinking` object.
    # None = don't send the flag (use the model default), True = force on, False = force off.
    use_thinking: Optional[bool] = None

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
    ) -> Dict[str, Any]:
        request_params = super().get_request_params(
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )

        if self.use_thinking is not None:
            # Merge with any user-supplied extra_body and never overwrite an explicit
            # thinking setting (so a raw extra_body override still takes precedence).
            extra_body = request_params.get("extra_body") or {}
            mode = "enabled" if self.use_thinking else "disabled"
            extra_body.setdefault("thinking", {"type": mode})
            request_params["extra_body"] = extra_body

            # With thinking off, reasoning_effort has no effect, so strip it.
            if not self.use_thinking:
                request_params.pop("reasoning_effort", None)

        return request_params

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("MOONSHOT_API_KEY")
            if not self.api_key:
                # Raise error immediately if key is missing
                raise ModelAuthenticationError(
                    message="MOONSHOT_API_KEY not set. Please set the MOONSHOT_API_KEY environment variable.",
                    model_name=self.name,
                )

        # Define base client params
        base_params = {
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

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        """Round-trip ``reasoning_content`` back to the API.

        Models that carry reasoning across turns expect prior assistant turns' reasoning
        to be sent back unchanged, so it is added to the outgoing message when present.
        """
        message_dict = super()._format_message(message, compress_tool_results)

        if message.reasoning_content is not None:
            message_dict["reasoning_content"] = message.reasoning_content

        return message_dict
