from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_debug, log_error


@dataclass
class Zhipu(OpenAILike):
    """Zhipu AI model compatible with OpenAI API format with enhanced features."""

    id: str = "glm-4.7"
    name: str = "Zhipu"
    provider: str = "Zhipu"

    api_key: Optional[str] = getenv("ZHIPU_API_KEY")
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"

    # Thinking mode configuration
    enable_thinking: bool = False
    supports_native_structured_outputs: bool = False

    def _configure_thinking_params(self) -> Dict[str, Any]:
        """Configure thinking parameters"""
        return {"type": "enabled"}

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("ZHIPU_API_KEY")
            if not self.api_key:
                raise ModelProviderError(
                    message="ZHIPU_API_KEY not set. Please set the ZHIPU_API_KEY environment variable.",
                    model_name=self.name,
                    model_id=self.id,
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

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Get request parameters with thinking mode support.
        """
        # Get base parameters (includes response_format handling from OpenAIChat)
        params = super().get_request_params(
            response_format=response_format, tools=tools, tool_choice=tool_choice, run_response=run_response, **kwargs
        )

        # Add thinking configuration
        if self.enable_thinking:
            if "extra_body" not in params:
                params["extra_body"] = {}
            params["extra_body"]["thinking"] = self._configure_thinking_params()

        return params

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """Enhanced non-streaming call with performance optimization."""
        # Ensure API key is set before calling parent invoke and log error early
        try:
            self._get_client_params()
        except ModelProviderError as e:
            log_error(e.message)
            raise e

        # Use agno's metrics system
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        assistant_message.metrics.start_timer()

        # Use agno's standard logging system - basic logging handled by base.py
        if self.request_params:
            log_debug(f"Calling {self.provider} with request parameters: {self.request_params}", log_level=2)

        # Execute request
        response = super().invoke(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        )

        assistant_message.metrics.stop_timer()
        return response

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
    ) -> Iterator[ModelResponse]:
        """Enhanced streaming call."""
        # Ensure API key is set before calling parent invoke and log error early
        try:
            self._get_client_params()
        except ModelProviderError as e:
            log_error(e.message)
            raise e

        # Use agno's metrics system
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        assistant_message.metrics.start_timer()

        # Use agno's standard logging system - basic logging handled by base.py
        if self.request_params:
            log_debug(f"Calling {self.provider} with request parameters: {self.request_params}", log_level=2)

        # Execute streaming request
        response_stream = super().invoke_stream(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        )

        # Handle streaming response
        for response in response_stream:
            yield response

        assistant_message.metrics.stop_timer()

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """Enhanced async non-streaming call."""
        # Ensure API key is set before calling parent invoke and log error early
        try:
            self._get_client_params()
        except ModelProviderError as e:
            log_error(e.message)
            raise e

        # Use agno's metrics system
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        assistant_message.metrics.start_timer()

        # Use agno's standard logging system - basic logging handled by base.py
        if self.request_params:
            log_debug(f"Calling {self.provider} with request parameters: {self.request_params}", log_level=2)

        # Execute async request
        response = await super().ainvoke(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        )

        assistant_message.metrics.stop_timer()
        return response

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        """Enhanced async streaming call."""
        # Ensure API key is set before calling parent invoke and log error early
        try:
            self._get_client_params()
        except ModelProviderError as e:
            log_error(e.message)
            raise e

        # Use agno's metrics system
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        assistant_message.metrics.start_timer()

        # Use agno's standard logging system - basic logging handled by base.py
        if self.request_params:
            log_debug(f"Calling {self.provider} with request parameters: {self.request_params}", log_level=2)

        # Execute async streaming request
        response_stream = super().ainvoke_stream(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        )

        # Handle streaming response
        async for response in response_stream:
            yield response

        assistant_message.metrics.stop_timer()
