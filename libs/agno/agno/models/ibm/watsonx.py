from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.models.watsonx import format_images_for_message

try:
    from ibm_watsonx_ai import Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference
except ImportError:
    raise ImportError("`ibm-watsonx-ai` is not installed. Please install it using `pip install ibm-watsonx-ai`.")


@dataclass
class WatsonX(Model):
    """
    A class for interacting with IBM WatsonX models.

    See supported models at: https://dataplatform.cloud.ibm.com/docs/content/wsj/analyze-data/fm-models.html?context=wx

    For more information, see: https://www.ibm.com/watsonx/developer/
    """

    id: str = "ibm/granite-20b-code-instruct"
    name: str = "WatsonX"
    provider: str = "IBM"

    # Request parameters
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    logprobs: Optional[int] = None
    top_logprobs: Optional[int] = None

    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    project_id: Optional[str] = None
    url: Optional[str] = "https://eu-de.ml.cloud.ibm.com"
    verify: bool = True
    client_params: Optional[Dict[str, Any]] = None

    # WatsonX client
    model_client: Optional[ModelInference] = None

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key and project ID from env if not already set
        self.api_key = self.api_key or getenv("IBM_WATSONX_API_KEY")
        if not self.api_key:
            log_error("IBM_WATSONX_API_KEY not set. Please set the IBM_WATSONX_API_KEY environment variable.")

        self.project_id = self.project_id or getenv("IBM_WATSONX_PROJECT_ID")
        if not self.project_id:
            log_error("IBM_WATSONX_PROJECT_ID not set. Please set the IBM_WATSONX_PROJECT_ID environment variable.")

        self.url = getenv("IBM_WATSONX_URL") or self.url

        # Create credentials object
        credentials = Credentials(url=self.url, api_key=self.api_key, verify=self.verify)

        return {
            "credentials": credentials,
            "project_id": self.project_id,
        }

    def get_client(self) -> ModelInference:
        """
        Returns a WatsonX ModelInference client.

        Returns:
            ModelInference: An instance of the WatsonX ModelInference client.
        """
        if self.model_client:
            return self.model_client

        # Get client parameters
        client_params = self._get_client_params()

        # Initialize model inference client
        self.model_client = ModelInference(model_id=self.id, **client_params)

        return self.model_client

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        params = {
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "logprobs": self.logprobs,
            "top_logprobs": self.top_logprobs,
            "response_format": response_format,
        }
        # Filter out None values
        params = {k: v for k, v in params.items() if v is not None}
        request_params = {}

        if params:
            request_params["params"] = params

        # Add tools
        if tools is not None:
            request_params["tools"] = tools  # type: ignore
            if tool_choice is not None:
                request_params["tool_choice"] = tool_choice  # type: ignore
        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)
        return request_params

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        """
        Format a message into the format expected by WatsonX.

        Args:
            message (Message): The message to format.
            compress_tool_results: Whether to compress tool results.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        if message.images is not None and isinstance(message.content, str):
            message = format_images_for_message(message=message, images=message.images)

        if message.audio is not None and len(message.audio) > 0:
            log_warning("Audio input is currently unsupported.")

        if message.files is not None and len(message.files) > 0:
            log_warning("File input is currently unsupported.")

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported.")

        message_dict = message.to_dict()

        # Use compressed content for tool messages if compression is active
        if message.role == "tool" and compress_tool_results:
            message_dict["content"] = message.get_content(use_compressed_content=True)
        return message_dict

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """
        Send a chat completion request to the WatsonX API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            client = self.get_client()

            formatted_messages = [self._format_message(m, compress_tool_results) for m in messages]
            request_params = self.get_request_params(
                response_format=response_format, tools=tools, tool_choice=tool_choice
            )

            assistant_message.metrics.start_timer()
            response = client.chat(messages=formatted_messages, **request_params)
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(response, response_format=response_format)

            return model_response

        except Exception as e:
            log_error(f"Error calling WatsonX API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> Any:
        """
        Sends an asynchronous chat completion request to the WatsonX API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            client = self.get_client()
            formatted_messages = [self._format_message(m, compress_tool_results) for m in messages]

            request_params = self.get_request_params(
                response_format=response_format, tools=tools, tool_choice=tool_choice
            )

            assistant_message.metrics.start_timer()
            provider_response = await client.achat(messages=formatted_messages, **request_params)
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(provider_response, response_format=response_format)

            return model_response

        except Exception as e:
            log_error(f"Error calling WatsonX API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> Iterator[ModelResponse]:
        """
        Send a streaming chat completion request to the WatsonX API.
        """
        try:
            client = self.get_client()
            formatted_messages = [self._format_message(m, compress_tool_results) for m in messages]

            request_params = self.get_request_params(
                response_format=response_format, tools=tools, tool_choice=tool_choice
            )

            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()

            for chunk in client.chat_stream(messages=formatted_messages, **request_params):
                yield self._parse_provider_response_delta(chunk)

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error calling WatsonX API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        """
        Sends an asynchronous streaming chat completion request to the WatsonX API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            client = self.get_client()
            formatted_messages = [self._format_message(m, compress_tool_results) for m in messages]

            # Get parameters for chat
            request_params = self.get_request_params(
                response_format=response_format, tools=tools, tool_choice=tool_choice
            )

            assistant_message.metrics.start_timer()

            async_stream = await client.achat_stream(messages=formatted_messages, **request_params)
            async for chunk in async_stream:
                yield self._parse_provider_response_delta(chunk)

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error in async streaming from WatsonX API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    # Override base method
    @staticmethod
    def parse_tool_calls(tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build tool calls from streamed tool call data.

        Args:
            tool_calls_data (List[ChoiceDeltaToolCall]): The tool call data to build from.

        Returns:
            List[Dict[str, Any]]: The built tool calls.
        """
        tool_calls: List[Dict[str, Any]] = []
        for _tool_call in tool_calls_data:
            _index = _tool_call.get("index", 0)
            _tool_call_id = _tool_call.get("id")
            _tool_call_type = _tool_call.get("type")
            _function_name = _tool_call.get("function", {}).get("name")
            _function_arguments = _tool_call.get("function", {}).get("arguments")

            if len(tool_calls) <= _index:
                tool_calls.extend([{}] * (_index - len(tool_calls) + 1))
            tool_call_entry = tool_calls[_index]
            if not tool_call_entry:
                tool_call_entry["id"] = _tool_call_id
                tool_call_entry["type"] = _tool_call_type
                tool_call_entry["function"] = {
                    "name": _function_name or "",
                    "arguments": _function_arguments or "",
                }
            else:
                if _function_name:
                    tool_call_entry["function"]["name"] += _function_name
                if _function_arguments:
                    tool_call_entry["function"]["arguments"] += _function_arguments
                if _tool_call_id:
                    tool_call_entry["id"] = _tool_call_id
                if _tool_call_type:
                    tool_call_entry["type"] = _tool_call_type
        return tool_calls

    def _parse_provider_response(
        self,
        response: Dict[str, Any],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        """
        Parse the WatsonX response into a ModelResponse.
        """
        model_response = ModelResponse()

        # Get response message
        response_message = response["choices"][0]["message"]
        # Parse structured outputs if enabled
        try:
            if (
                response_format is not None
                and isinstance(response_format, type)
                and issubclass(response_format, BaseModel)
            ):
                parsed_object = response_message.parsed  # type: ignore
                if parsed_object is not None:
                    model_response.parsed = parsed_object
        except Exception as e:
            log_warning(f"Error retrieving structured outputs: {e}")

        # Add role
        if response_message.get("role") is not None:
            model_response.role = response_message["role"]

        # Add content
        if response_message.get("content") is not None:
            model_response.content = response_message["content"]

        # Add tool calls
        if response_message.get("tool_calls") is not None and len(response_message["tool_calls"]) > 0:
            try:
                model_response.tool_calls = response_message["tool_calls"]
            except Exception as e:
                log_warning(f"Error processing tool calls: {e}")

        if response.get("usage") is not None:
            model_response.response_usage = self._get_metrics(response["usage"])

        return model_response

    def _parse_provider_response_delta(self, response_delta: Dict[str, Any]) -> ModelResponse:
        """
        Parse the OpenAI streaming response into a ModelResponse.
        """
        model_response = ModelResponse()

        if response_delta.get("choices") and len(response_delta["choices"]) > 0:
            choice_delta: Dict[str, Any] = response_delta["choices"][0].get("delta")

            if choice_delta:
                # Add content
                if choice_delta.get("content") is not None:
                    model_response.content = choice_delta["content"]

                # Add tool calls
                if choice_delta.get("tool_calls") is not None:
                    model_response.tool_calls = choice_delta["tool_calls"]

        # Add usage metrics if present
        if response_delta.get("usage") is not None:
            model_response.response_usage = self._get_metrics(response_delta["usage"])

        return model_response

    def _get_metrics(self, response_usage: Dict[str, Any]) -> Metrics:
        """
        Parse the given WatsonX usage into an Agno Metrics object.

        Args:
            response_usage: Usage data from WatsonX

        Returns:
            Metrics: Parsed metrics data
        """
        metrics = Metrics()

        metrics.input_tokens = response_usage.get("prompt_tokens") or 0
        metrics.output_tokens = response_usage.get("completion_tokens") or 0
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        return metrics
