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
from agno.utils.log import log_debug, log_error
from agno.utils.models.openai import format_messages

try:
    from openai import AsyncOpenAI, OpenAI
    from openai import APIError as OpenAIAPIError
    from openai.types.chat import ChatCompletion, ChatCompletionChunk
except ImportError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class Pollinations(Model):
    """
    Pollinations is a model provider that uses the Pollinations AI API.
    For more information, see: https://enter.pollinations.ai/api/docs
    """

    id: str = "openai"
    name: str = "Pollinations"
    provider: str = "Pollinations"
   
# Request parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    seed: Optional[int] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    base_url: str = "https://gen.pollinations.ai/v1"
    max_retries: Optional[int] = None
    timeout: Optional[int] = None
    client_params: Optional[Dict[str, Any]] = None

    # Provide the OpenAI client manually (for Pollinations API compatibility)
    openai_client: Optional[OpenAI] = None
    async_openai_client: Optional[AsyncOpenAI] = None

    def get_client(self) -> OpenAI:
        """
        Get the OpenAI client for Pollinations API.
        
        Returns:
            OpenAI: The OpenAI client instance configured for Pollinations.
        """
        if self.openai_client:
            return self.openai_client

        _client_params = self._get_client_params()
        self.openai_client = OpenAI(**_client_params)
        return self.openai_client

    def get_async_client(self) -> AsyncOpenAI:
        """
        Get the async OpenAI client for Pollinations API.
        
        Returns:
            AsyncOpenAI: The async OpenAI client instance configured for Pollinations.
        """
        if self.async_openai_client:
            return self.async_openai_client

        _client_params = self._get_client_params()
        self.async_openai_client = AsyncOpenAI(**_client_params)
        return self.async_openai_client

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Get the client parameters for initializing OpenAI clients.
        
        Returns:
            Dict[str, Any]: The client parameters.
        """
        client_params: Dict[str, Any] = {}
        
        self.api_key = self.api_key or getenv("POLLINATIONS_API_KEY")
        if not self.api_key:
            log_error("POLLINATIONS_API_KEY not set. Please set the POLLINATIONS_API_KEY environment variable.")
        
        client_params.update(
            {
                "api_key": self.api_key,
                "base_url": self.base_url,
                "max_retries": self.max_retries,
                "timeout": self.timeout,
            }
        )
        
        if self.client_params is not None:
            client_params.update(self.client_params)
        
        # Remove None values
        return {k: v for k, v in client_params.items() if v is not None}

    def get_request_params(
        self, tools: Optional[List[Dict[str, Any]]] = None, tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Get the API kwargs for the Pollinations model.
        
        Returns:
            Dict[str, Any]: The API kwargs.
        """
        _request_params: Dict[str, Any] = {}
        
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.seed:
            _request_params["seed"] = self.seed
        
        if tools:
            _request_params["tools"] = tools
            if tool_choice is None:
                _request_params["tool_choice"] = "auto"
            else:
                _request_params["tool_choice"] = tool_choice
        
        if self.request_params:
            _request_params.update(self.request_params)
        
        if _request_params:
            log_debug(f"Calling {self.provider} with request parameters: {_request_params}", log_level=2)
        
        return _request_params

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.
        
        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        _dict = super().to_dict()
        _dict.update(
            {
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "seed": self.seed,
            }
        )
        cleaned_dict = {k: v for k, v in _dict.items() if v is not None}
        return cleaned_dict

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
        Send a chat completion request to the Pollinations model.
        """
        openai_messages = format_messages(messages, compress_tool_results)
        
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()
            assistant_message.metrics.start_timer()
            
            response: ChatCompletion = self.get_client().chat.completions.create(
                model=self.id,
                messages=openai_messages,
                **self.get_request_params(tools=tools, tool_choice=tool_choice),
            )
            
            assistant_message.metrics.stop_timer()
            model_response = self._parse_provider_response(response)
            return model_response
        except OpenAIAPIError as e:
            log_error(f"OpenAIAPIError from Pollinations: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Error from Pollinations: {e}")
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
        Stream the response from the Pollinations model.
        """
        openai_messages = format_messages(messages, compress_tool_results)
        
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()
        assistant_message.metrics.start_timer()
        
        try:
            for chunk in self.get_client().chat.completions.create(
                model=self.id,
                messages=openai_messages,
                stream=True,
                **self.get_request_params(tools=tools, tool_choice=tool_choice),
            ):
                yield self._parse_provider_response_delta(chunk)
            assistant_message.metrics.stop_timer()
        except OpenAIAPIError as e:
            log_error(f"OpenAIAPIError from Pollinations: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Error from Pollinations: {e}")
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
    ) -> ModelResponse:
        """
        Send an asynchronous chat completion request to the Pollinations API.
        """
        openai_messages = format_messages(messages, compress_tool_results)
        
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()
            assistant_message.metrics.start_timer()
            
            response: ChatCompletion = await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=openai_messages,
                **self.get_request_params(tools=tools, tool_choice=tool_choice),
            )
            
            assistant_message.metrics.stop_timer()
            model_response = self._parse_provider_response(response)
            return model_response
        except OpenAIAPIError as e:
            log_error(f"OpenAIAPIError from Pollinations: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Error from Pollinations: {e}")
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
        Stream an asynchronous response from the Pollinations API.
        """
        openai_messages = format_messages(messages, compress_tool_results)
        
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()
            assistant_message.metrics.start_timer()
            
            async for chunk in await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=openai_messages,
                stream=True,
                **self.get_request_params(tools=tools, tool_choice=tool_choice),
            ):
                yield self._parse_provider_response_delta(chunk)
            assistant_message.metrics.stop_timer()
        except OpenAIAPIError as e:
            log_error(f"OpenAIAPIError from Pollinations: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Error from Pollinations: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def _parse_provider_response(self, response: ChatCompletion) -> ModelResponse:
        """
        Parse the response from the Pollinations model.
        
        Args:
            response (ChatCompletion): The response from the model.
        """
        model_response = ModelResponse()
        
        if response.choices is not None and len(response.choices) > 0:
            response_message = response.choices[0].message
            
            # Set content
            model_response.content = response_message.content
            
            # Set role
            model_response.role = response_message.role
            
            # Set tool calls
            if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
                model_response.tool_calls = []
                for tool_call in response_message.tool_calls:
                    model_response.tool_calls.append(
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                    )
        
        if response.usage is not None:
            model_response.response_usage = self._get_metrics(response.usage)
        
        return model_response

    def _parse_provider_response_delta(self, response_delta: ChatCompletionChunk) -> ModelResponse:
        """
        Parse the response delta from the Pollinations model.
        """
        model_response = ModelResponse()
        
        if response_delta.choices is not None and len(response_delta.choices) > 0:
            delta_message = response_delta.choices[0].delta
            
            if delta_message.role is not None:
                model_response.role = delta_message.role
            
            if delta_message.content is not None:
                model_response.content = delta_message.content
            
            if delta_message.tool_calls is not None:
                model_response.tool_calls = []
                for tool_call in delta_message.tool_calls:
                    model_response.tool_calls.append(
                        {
                            "id": tool_call.id if hasattr(tool_call, 'id') and tool_call.id else None,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name if hasattr(tool_call.function, 'name') else None,
                                "arguments": tool_call.function.arguments if hasattr(tool_call.function, 'arguments') else None,
                            },
                        }
                    )
        
        if hasattr(response_delta, 'usage') and response_delta.usage is not None:
            model_response.response_usage = self._get_metrics(response_delta.usage)
        
        return model_response

    def _get_metrics(self, response_usage: Any) -> Metrics:
        """
        Parse the given Pollinations usage into an Agno Metrics object.
        
        Args:
            response_usage: Usage data from Pollinations
        
        Returns:
            Metrics: Parsed metrics data
        """
        metrics = Metrics()
        metrics.input_tokens = response_usage.prompt_tokens or 0
        metrics.output_tokens = response_usage.completion_tokens or 0
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens
        return metrics
