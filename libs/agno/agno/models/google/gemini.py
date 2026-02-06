import asyncio
import base64
import json
import mimetypes
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Type, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import Audio, File, Image, Video
from agno.models.base import Model, RetryableModelProviderError
from agno.models.google.utils import MALFORMED_FUNCTION_CALL_GUIDANCE, GeminiFinishReason
from agno.models.message import Citations, Message, UrlCitation
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.tools.function import Function
from agno.utils.gemini import format_function_definitions, format_image_for_message, prepare_response_schema
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.tokens import count_schema_tokens, count_text_tokens, count_tool_tokens

try:
    from google import genai
    from google.genai import Client as GeminiClient
    from google.genai.errors import ClientError, ServerError
    from google.genai.types import (
        Content,
        DynamicRetrievalConfig,
        FileSearch,
        FunctionCallingConfigMode,
        GenerateContentConfig,
        GenerateContentResponse,
        GenerateContentResponseUsageMetadata,
        GoogleSearch,
        GoogleSearchRetrieval,
        GroundingMetadata,
        Operation,
        Part,
        Retrieval,
        ThinkingConfig,
        Tool,
        UrlContext,
        VertexAISearch,
    )
    from google.genai.types import (
        File as GeminiFile,
    )
    from google.oauth2.service_account import Credentials
except ImportError:
    raise ImportError(
        "`google-genai` not installed or not at the latest version. Please install it using `pip install -U google-genai`"
    )


@dataclass
class Gemini(Model):
    """
    Gemini model class for Google's Generative AI models.

    Vertex AI:
    - You will need Google Cloud credentials to use the Vertex AI API. Run `gcloud auth application-default login` to set credentials.
    - Set `vertexai` to `True` to use the Vertex AI API.
    - Set your `project_id` (or set `GOOGLE_CLOUD_PROJECT` environment variable) and `location` (optional).
    - Set `http_options` (optional) to configure the HTTP options.
    - Set `credentials` (optional) to use the Google Cloud credentials.

    Based on https://googleapis.github.io/python-genai/
    """

    id: str = "gemini-2.0-flash-001"
    name: str = "Gemini"
    provider: str = "Google"

    supports_native_structured_outputs: bool = True

    # Request parameters
    function_declarations: Optional[List[Any]] = None
    generation_config: Optional[Any] = None
    safety_settings: Optional[List[Any]] = None
    generative_model_kwargs: Optional[Dict[str, Any]] = None
    search: bool = False
    grounding: bool = False
    grounding_dynamic_threshold: Optional[float] = None
    url_context: bool = False
    vertexai_search: bool = False
    vertexai_search_datastore: Optional[str] = None

    # Gemini File Search capabilities
    file_search_store_names: Optional[List[str]] = None
    file_search_metadata_filter: Optional[str] = None

    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_output_tokens: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    logprobs: Optional[bool] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    seed: Optional[int] = None
    response_modalities: Optional[list[str]] = None  # "TEXT", "IMAGE", and/or "AUDIO"
    speech_config: Optional[dict[str, Any]] = None
    cached_content: Optional[Any] = None
    thinking_budget: Optional[int] = None  # Thinking budget for Gemini 2.5 models
    include_thoughts: Optional[bool] = None  # Include thought summaries in response
    thinking_level: Optional[str] = None  # "low", "high"
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    credentials: Optional[Credentials] = None
    api_key: Optional[str] = None
    vertexai: bool = False
    project_id: Optional[str] = None
    location: Optional[str] = None
    client_params: Optional[Dict[str, Any]] = None

    # Gemini client
    client: Optional[GeminiClient] = None

    # The role to map the Gemini response
    role_map = {
        "model": "assistant",
    }

    # The role to map the Message
    reverse_role_map = {
        "assistant": "model",
        "tool": "user",
    }

    def get_client(self) -> GeminiClient:
        """
        Returns an instance of the GeminiClient client.

        Returns:
            GeminiClient: The GeminiClient client.
        """
        if self.client:
            return self.client
        client_params: Dict[str, Any] = {}
        vertexai = self.vertexai or getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"

        if not vertexai:
            self.api_key = self.api_key or getenv("GOOGLE_API_KEY")
            if not self.api_key:
                log_error("GOOGLE_API_KEY not set. Please set the GOOGLE_API_KEY environment variable.")
            client_params["api_key"] = self.api_key
        else:
            log_info("Using Vertex AI API")
            client_params["vertexai"] = True
            project_id = self.project_id or getenv("GOOGLE_CLOUD_PROJECT")
            if not project_id:
                log_error("GOOGLE_CLOUD_PROJECT not set. Please set the GOOGLE_CLOUD_PROJECT environment variable.")
            location = self.location or getenv("GOOGLE_CLOUD_LOCATION")
            if not location:
                log_error("GOOGLE_CLOUD_LOCATION not set. Please set the GOOGLE_CLOUD_LOCATION environment variable.")
            client_params["project"] = project_id
            client_params["location"] = location
            if self.credentials:
                client_params["credentials"] = self.credentials

        client_params = {k: v for k, v in client_params.items() if v is not None}

        if self.client_params:
            client_params.update(self.client_params)

        self.client = genai.Client(**client_params)
        return self.client

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        model_dict = super().to_dict()
        model_dict.update(
            {
                "search": self.search,
                "grounding": self.grounding,
                "grounding_dynamic_threshold": self.grounding_dynamic_threshold,
                "url_context": self.url_context,
                "vertexai_search": self.vertexai_search,
                "vertexai_search_datastore": self.vertexai_search_datastore,
                "file_search_store_names": self.file_search_store_names,
                "file_search_metadata_filter": self.file_search_metadata_filter,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "max_output_tokens": self.max_output_tokens,
                "stop_sequences": self.stop_sequences,
                "logprobs": self.logprobs,
                "presence_penalty": self.presence_penalty,
                "frequency_penalty": self.frequency_penalty,
                "seed": self.seed,
                "response_modalities": self.response_modalities,
                "thinking_budget": self.thinking_budget,
                "include_thoughts": self.include_thoughts,
                "thinking_level": self.thinking_level,
                "vertexai": self.vertexai,
                "project_id": self.project_id,
                "location": self.location,
            }
        )
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def _append_file_search_tool(self, builtin_tools: List[Tool]) -> None:
        """Append Gemini File Search tool to builtin_tools if file search is enabled.

        Args:
            builtin_tools: List of built-in tools to append to.
        """
        if not self.file_search_store_names:
            return

        log_debug("Gemini File Search enabled.")
        file_search_config: Dict[str, Any] = {"file_search_store_names": self.file_search_store_names}
        if self.file_search_metadata_filter:
            file_search_config["metadata_filter"] = self.file_search_metadata_filter
        builtin_tools.append(Tool(file_search=FileSearch(**file_search_config)))  # type: ignore[arg-type]

    def get_request_params(
        self,
        system_message: Optional[str] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns the request keyword arguments for the GenerativeModel client.
        """
        request_params = {}
        # User provides their own generation config
        if self.generation_config is not None:
            if isinstance(self.generation_config, GenerateContentConfig):
                config = self.generation_config.model_dump()
            else:
                config = self.generation_config
        else:
            config = {}

        if self.generative_model_kwargs:
            config.update(self.generative_model_kwargs)

        config.update(
            {
                "safety_settings": self.safety_settings,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "max_output_tokens": self.max_output_tokens,
                "stop_sequences": self.stop_sequences,
                "logprobs": self.logprobs,
                "presence_penalty": self.presence_penalty,
                "frequency_penalty": self.frequency_penalty,
                "seed": self.seed,
                "response_modalities": self.response_modalities,
                "speech_config": self.speech_config,
                "cached_content": self.cached_content,
            }
        )

        if system_message is not None:
            config["system_instruction"] = system_message  # type: ignore

        if response_format is not None and isinstance(response_format, type) and issubclass(response_format, BaseModel):
            config["response_mime_type"] = "application/json"  # type: ignore
            # Convert Pydantic model using our hybrid approach
            # This will handle complex schemas with nested models, dicts, and circular refs
            config["response_schema"] = prepare_response_schema(response_format)

        # Add thinking configuration
        thinking_config_params: Dict[str, Any] = {}
        if self.thinking_budget is not None:
            thinking_config_params["thinking_budget"] = self.thinking_budget
        if self.include_thoughts is not None:
            thinking_config_params["include_thoughts"] = self.include_thoughts
        if self.thinking_level is not None:
            thinking_config_params["thinking_level"] = self.thinking_level
        if thinking_config_params:
            config["thinking_config"] = ThinkingConfig(**thinking_config_params)

        # Build tools array based on enabled built-in tools
        builtin_tools = []

        if self.grounding:
            log_debug(
                "Gemini Grounding enabled. This is a legacy tool. For Gemini 2.0+ Please use enable `search` flag instead."
            )
            builtin_tools.append(
                Tool(
                    google_search=GoogleSearchRetrieval(
                        dynamic_retrieval_config=DynamicRetrievalConfig(
                            dynamic_threshold=self.grounding_dynamic_threshold
                        )
                    )
                )
            )

        if self.search:
            log_debug("Gemini Google Search enabled.")
            builtin_tools.append(Tool(google_search=GoogleSearch()))

        if self.url_context:
            log_debug("Gemini URL context enabled.")
            builtin_tools.append(Tool(url_context=UrlContext()))

        if self.vertexai_search:
            log_debug("Gemini Vertex AI Search enabled.")
            if not self.vertexai_search_datastore:
                log_error("vertexai_search_datastore must be provided when vertexai_search is enabled.")
                raise ValueError("vertexai_search_datastore must be provided when vertexai_search is enabled.")
            builtin_tools.append(
                Tool(retrieval=Retrieval(vertex_ai_search=VertexAISearch(datastore=self.vertexai_search_datastore)))
            )

        self._append_file_search_tool(builtin_tools)

        # Set tools in config
        if builtin_tools:
            if tools:
                log_info("Built-in tools enabled. External tools will be disabled.")
            config["tools"] = builtin_tools
        elif tools:
            config["tools"] = [format_function_definitions(tools)]

        if tool_choice is not None:
            if isinstance(tool_choice, str) and tool_choice.lower() == "auto":
                config["tool_config"] = {"function_calling_config": {"mode": FunctionCallingConfigMode.AUTO}}
            elif isinstance(tool_choice, str) and tool_choice.lower() == "none":
                config["tool_config"] = {"function_calling_config": {"mode": FunctionCallingConfigMode.NONE}}
            elif isinstance(tool_choice, str) and tool_choice.lower() == "validated":
                config["tool_config"] = {"function_calling_config": {"mode": FunctionCallingConfigMode.VALIDATED}}
            elif isinstance(tool_choice, str) and tool_choice.lower() == "any":
                config["tool_config"] = {"function_calling_config": {"mode": FunctionCallingConfigMode.ANY}}
            else:
                config["tool_config"] = {"function_calling_config": {"mode": tool_choice}}

        config = {k: v for k, v in config.items() if v is not None}

        if config:
            request_params["config"] = GenerateContentConfig(**config)

        # Filter out None values
        if self.request_params:
            request_params.update(self.request_params)

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)
        return request_params

    def count_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        output_schema: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        contents, system_instruction = self._format_messages(messages, compress_tool_results=True)
        schema_tokens = count_schema_tokens(output_schema, self.id)

        if self.vertexai:
            # VertexAI supports full token counting with system_instruction and tools
            config: Dict[str, Any] = {}
            if system_instruction:
                config["system_instruction"] = system_instruction
            if tools:
                formatted_tools = self._format_tools(tools)
                gemini_tools = format_function_definitions(formatted_tools)
                if gemini_tools:
                    config["tools"] = [gemini_tools]

            response = self.get_client().models.count_tokens(
                model=self.id,
                contents=contents,
                config=config if config else None,  # type: ignore
            )
            return (response.total_tokens or 0) + schema_tokens
        else:
            # Google AI Studio: Use API for content tokens + local estimation for system/tools
            # The API doesn't support system_instruction or tools in config, so we use a hybrid approach:
            # 1. Get accurate token count for contents (text + multimodal) from API
            # 2. Add estimated tokens for system_instruction and tools locally
            try:
                response = self.get_client().models.count_tokens(
                    model=self.id,
                    contents=contents,
                )
                total = response.total_tokens or 0
            except Exception as e:
                log_warning(f"Gemini count_tokens API failed: {e}. Falling back to tiktoken-based estimation.")
                return super().count_tokens(messages, tools, output_schema)

            # Add estimated tokens for system instruction (not supported by Google AI Studio API)
            if system_instruction:
                system_text = system_instruction if isinstance(system_instruction, str) else str(system_instruction)
                total += count_text_tokens(system_text, self.id)

            # Add estimated tokens for tools (not supported by Google AI Studio API)
            if tools:
                total += count_tool_tokens(tools, self.id)

            # Add estimated tokens for response_format/output_schema
            total += schema_tokens

            return total

    async def acount_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        output_schema: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        contents, system_instruction = self._format_messages(messages, compress_tool_results=True)
        schema_tokens = count_schema_tokens(output_schema, self.id)

        # VertexAI supports full token counting with system_instruction and tools
        if self.vertexai:
            config: Dict[str, Any] = {}
            if system_instruction:
                config["system_instruction"] = system_instruction
            if tools:
                formatted_tools = self._format_tools(tools)
                gemini_tools = format_function_definitions(formatted_tools)
                if gemini_tools:
                    config["tools"] = [gemini_tools]

            response = await self.get_client().aio.models.count_tokens(
                model=self.id,
                contents=contents,
                config=config if config else None,  # type: ignore
            )
            return (response.total_tokens or 0) + schema_tokens
        else:
            # Hybrid approach - Google AI Studio does not support system_instruction or tools in config
            try:
                response = await self.get_client().aio.models.count_tokens(
                    model=self.id,
                    contents=contents,
                )
                total = response.total_tokens or 0
            except Exception as e:
                log_warning(f"Gemini count_tokens API failed: {e}. Falling back to tiktoken-based estimation.")
                return await super().acount_tokens(messages, tools, output_schema)

            # Add estimated tokens for system instruction
            if system_instruction:
                system_text = system_instruction if isinstance(system_instruction, str) else str(system_instruction)
                total += count_text_tokens(system_text, self.id)

            # Add estimated tokens for tools
            if tools:
                total += count_tool_tokens(tools, self.id)

            # Add estimated tokens for response_format/output_schema
            total += schema_tokens

            return total

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
        retry_with_guidance: bool = False,
    ) -> ModelResponse:
        """
        Invokes the model with a list of messages and returns the response.
        """
        formatted_messages, system_message = self._format_messages(messages, compress_tool_results)
        request_kwargs = self.get_request_params(
            system_message, response_format=response_format, tools=tools, tool_choice=tool_choice
        )
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()
            provider_response = self.get_client().models.generate_content(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(
                provider_response, response_format=response_format, retry_with_guidance=retry_with_guidance
            )

            # If we were retrying the invoke with guidance, remove the guidance message
            if retry_with_guidance is True:
                self._remove_temporary_messages(messages)

            return model_response

        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            error_message = str(e)
            if hasattr(e, "response"):
                if hasattr(e.response, "text"):
                    error_message = e.response.text
                else:
                    error_message = str(e.response)
            raise ModelProviderError(
                message=error_message,
                status_code=e.code if hasattr(e, "code") and e.code is not None else 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except RetryableModelProviderError:
            raise
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
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
        retry_with_guidance: bool = False,
    ) -> Iterator[ModelResponse]:
        """
        Invokes the model with a list of messages and returns the response as a stream.
        """
        formatted_messages, system_message = self._format_messages(messages, compress_tool_results)

        request_kwargs = self.get_request_params(
            system_message, response_format=response_format, tools=tools, tool_choice=tool_choice
        )
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()
            for response in self.get_client().models.generate_content_stream(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            ):
                yield self._parse_provider_response_delta(response, retry_with_guidance=retry_with_guidance)

            # If we were retrying the invoke with guidance, remove the guidance message
            if retry_with_guidance is True:
                self._remove_temporary_messages(messages)

            assistant_message.metrics.stop_timer()

        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            error_message = str(e)
            if hasattr(e, "response"):
                if hasattr(e.response, "text"):
                    error_message = e.response.text
                else:
                    error_message = str(e.response)
            raise ModelProviderError(
                message=error_message,
                status_code=e.code if hasattr(e, "code") and e.code is not None else 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except RetryableModelProviderError:
            raise
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
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
        retry_with_guidance: bool = False,
    ) -> ModelResponse:
        """
        Invokes the model with a list of messages and returns the response.
        """
        formatted_messages, system_message = self._format_messages(messages, compress_tool_results)

        request_kwargs = self.get_request_params(
            system_message, response_format=response_format, tools=tools, tool_choice=tool_choice
        )

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()
            provider_response = await self.get_client().aio.models.generate_content(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(
                provider_response, response_format=response_format, retry_with_guidance=retry_with_guidance
            )

            # If we were retrying the invoke with guidance, remove the guidance message
            if retry_with_guidance is True:
                self._remove_temporary_messages(messages)

            return model_response

        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            error_message = str(e)
            if hasattr(e, "response"):
                if hasattr(e.response, "text"):
                    error_message = e.response.text
                else:
                    error_message = str(e.response)
            raise ModelProviderError(
                message=error_message,
                status_code=e.code if hasattr(e, "code") and e.code is not None else 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except RetryableModelProviderError:
            raise
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
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
        retry_with_guidance: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        """
        Invokes the model with a list of messages and returns the response as a stream.
        """
        formatted_messages, system_message = self._format_messages(messages, compress_tool_results)

        request_kwargs = self.get_request_params(
            system_message, response_format=response_format, tools=tools, tool_choice=tool_choice
        )

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()

            async_stream = await self.get_client().aio.models.generate_content_stream(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
            async for chunk in async_stream:
                yield self._parse_provider_response_delta(chunk, retry_with_guidance=retry_with_guidance)

            # If we were retrying the invoke with guidance, remove the guidance message
            if retry_with_guidance is True:
                self._remove_temporary_messages(messages)

            assistant_message.metrics.stop_timer()

        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            error_message = str(e)
            if hasattr(e, "response"):
                if hasattr(e.response, "text"):
                    error_message = e.response.text
                else:
                    error_message = str(e.response)
            raise ModelProviderError(
                message=error_message,
                status_code=e.code if hasattr(e, "code") and e.code is not None else 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except RetryableModelProviderError:
            raise
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def _format_messages(self, messages: List[Message], compress_tool_results: bool = False):
        """
        Converts a list of Message objects to the Gemini-compatible format.

        Args:
            messages (List[Message]): The list of messages to convert.
            compress_tool_results: Whether to compress tool results.
        """
        formatted_messages: List = []
        system_message = None

        for message in messages:
            role = message.role
            if role in ["system", "developer"]:
                system_message = message.content
                continue

            # Set the role for the message according to Gemini's requirements
            role = self.reverse_role_map.get(role, role)

            # Add content to the message for the model
            content = message.get_content(use_compressed_content=compress_tool_results)

            # Initialize message_parts to be used for Gemini
            message_parts: List[Any] = []

            # Function calls
            if role == "model" and message.tool_calls is not None and len(message.tool_calls) > 0:
                if content is not None:
                    content_str = content if isinstance(content, str) else str(content)
                    part = Part.from_text(text=content_str)
                    if message.provider_data and "thought_signature" in message.provider_data:
                        part.thought_signature = base64.b64decode(message.provider_data["thought_signature"])
                    message_parts.append(part)
                for tool_call in message.tool_calls:
                    part = Part.from_function_call(
                        name=tool_call["function"]["name"],
                        args=json.loads(tool_call["function"]["arguments"]),
                    )
                    if "thought_signature" in tool_call:
                        part.thought_signature = base64.b64decode(tool_call["thought_signature"])
                    message_parts.append(part)
            # Function call results
            elif message.tool_calls is not None and len(message.tool_calls) > 0:
                for idx, tool_call in enumerate(message.tool_calls):
                    if isinstance(content, list) and idx < len(content):
                        original_from_list = content[idx]

                        if compress_tool_results:
                            compressed_from_tool_call = tool_call.get("content")
                            tc_content = compressed_from_tool_call if compressed_from_tool_call else original_from_list
                        else:
                            tc_content = original_from_list
                    else:
                        tc_content = message.get_content(use_compressed_content=compress_tool_results)

                        if tc_content is None:
                            tc_content = tool_call.get("content")
                            if tc_content is None:
                                tc_content = content

                    message_parts.append(
                        Part.from_function_response(name=tool_call["tool_name"], response={"result": tc_content})
                    )
            # Regular text content
            else:
                if isinstance(content, str):
                    part = Part.from_text(text=content)
                    if message.provider_data and "thought_signature" in message.provider_data:
                        part.thought_signature = base64.b64decode(message.provider_data["thought_signature"])
                    message_parts = [part]

            if role == "user" and message.tool_calls is None:
                # Add images to the message for the model
                if message.images is not None:
                    for image in message.images:
                        if image.content is not None and isinstance(image.content, GeminiFile):
                            # Google recommends that if using a single image, place the text prompt after the image.
                            message_parts.insert(0, image.content)
                        else:
                            image_content = format_image_for_message(image)
                            if image_content:
                                message_parts.append(Part.from_bytes(**image_content))

                # Add videos to the message for the model
                if message.videos is not None:
                    try:
                        for video in message.videos:
                            # Case 1: Video is a file_types.File object (Recommended)
                            # Add it as a File object
                            if video.content is not None and isinstance(video.content, GeminiFile):
                                # Google recommends that if using a single video, place the text prompt after the video.
                                if video.content.uri and video.content.mime_type:
                                    message_parts.insert(
                                        0, Part.from_uri(file_uri=video.content.uri, mime_type=video.content.mime_type)
                                    )
                            else:
                                video_file = self._format_video_for_message(video)
                                if video_file is not None:
                                    message_parts.insert(0, video_file)
                    except Exception as e:
                        log_warning(f"Failed to load video from {message.videos}: {e}")
                        continue

                # Add audio to the message for the model
                if message.audio is not None:
                    try:
                        for audio_snippet in message.audio:
                            if audio_snippet.content is not None and isinstance(audio_snippet.content, GeminiFile):
                                # Google recommends that if using a single audio file, place the text prompt after the audio file.
                                if audio_snippet.content.uri and audio_snippet.content.mime_type:
                                    message_parts.insert(
                                        0,
                                        Part.from_uri(
                                            file_uri=audio_snippet.content.uri,
                                            mime_type=audio_snippet.content.mime_type,
                                        ),
                                    )
                            else:
                                audio_content = self._format_audio_for_message(audio_snippet)
                                if audio_content:
                                    message_parts.append(audio_content)
                    except Exception as e:
                        log_warning(f"Failed to load audio from {message.audio}: {e}")
                        continue

                # Add files to the message for the model
                if message.files is not None:
                    for file in message.files:
                        file_content = self._format_file_for_message(file)
                        if isinstance(file_content, Part):
                            message_parts.append(file_content)

            final_message = Content(role=role, parts=message_parts)
            formatted_messages.append(final_message)

        return formatted_messages, system_message

    def _format_audio_for_message(self, audio: Audio) -> Optional[Union[Part, GeminiFile]]:
        # Case 1: Audio is a bytes object
        if audio.content and isinstance(audio.content, bytes):
            mime_type = f"audio/{audio.format}" if audio.format else "audio/mp3"
            return Part.from_bytes(mime_type=mime_type, data=audio.content)

        # Case 2: Audio is an url
        elif audio.url is not None:
            audio_bytes = audio.get_content_bytes()  # type: ignore
            if audio_bytes is not None:
                mime_type = f"audio/{audio.format}" if audio.format else "audio/mp3"
                return Part.from_bytes(mime_type=mime_type, data=audio_bytes)
            else:
                log_warning(f"Failed to download audio from {audio}")
                return None

        # Case 3: Audio is a local file path
        elif audio.filepath is not None:
            audio_path = audio.filepath if isinstance(audio.filepath, Path) else Path(audio.filepath)

            remote_file_name = f"files/{audio_path.stem.lower().replace('_', '')}"
            # Check if video is already uploaded
            existing_audio_upload = None
            try:
                if remote_file_name:
                    existing_audio_upload = self.get_client().files.get(name=remote_file_name)
            except Exception as e:
                log_warning(f"Error getting file {remote_file_name}: {e}")

            if existing_audio_upload and existing_audio_upload.state and existing_audio_upload.state.name == "SUCCESS":
                audio_file = existing_audio_upload
            else:
                # Upload the video file to the Gemini API
                if audio_path.exists() and audio_path.is_file():
                    audio_file = self.get_client().files.upload(
                        file=audio_path,
                        config=dict(
                            name=remote_file_name,
                            display_name=audio_path.stem,
                            mime_type=f"audio/{audio.format}" if audio.format else "audio/mp3",
                        ),
                    )
                else:
                    log_error(f"Audio file {audio_path} does not exist.")
                    return None

                # Check whether the file is ready to be used.
                while audio_file.state and audio_file.state.name == "PROCESSING":
                    if audio_file.name:
                        audio_file = self.get_client().files.get(name=audio_file.name)
                    time.sleep(2)

                if audio_file.state and audio_file.state.name == "FAILED":
                    log_error(f"Audio file processing failed: {audio_file.state.name}")
                    return None

            if audio_file.uri:
                mime_type = f"audio/{audio.format}" if audio.format else "audio/mp3"
                return Part.from_uri(file_uri=audio_file.uri, mime_type=mime_type)
            return None
        else:
            log_warning(f"Unknown audio type: {type(audio.content)}")
            return None

    def _format_video_for_message(self, video: Video) -> Optional[Part]:
        # Case 1: Video is a bytes object
        if video.content and isinstance(video.content, bytes):
            mime_type = f"video/{video.format}" if video.format else "video/mp4"
            return Part.from_bytes(mime_type=mime_type, data=video.content)
        # Case 2: Video is stored locally
        elif video.filepath is not None:
            video_path = video.filepath if isinstance(video.filepath, Path) else Path(video.filepath)

            remote_file_name = f"files/{video_path.stem.lower().replace('_', '')}"
            # Check if video is already uploaded
            existing_video_upload = None
            try:
                if remote_file_name:
                    existing_video_upload = self.get_client().files.get(name=remote_file_name)
            except Exception as e:
                log_warning(f"Error getting file {remote_file_name}: {e}")

            if existing_video_upload and existing_video_upload.state and existing_video_upload.state.name == "SUCCESS":
                video_file = existing_video_upload
            else:
                # Upload the video file to the Gemini API
                if video_path.exists() and video_path.is_file():
                    video_file = self.get_client().files.upload(
                        file=video_path,
                        config=dict(
                            name=remote_file_name,
                            display_name=video_path.stem,
                            mime_type=f"video/{video.format}" if video.format else "video/mp4",
                        ),
                    )
                else:
                    log_error(f"Video file {video_path} does not exist.")
                    return None

                # Check whether the file is ready to be used.
                while video_file.state and video_file.state.name == "PROCESSING":
                    if video_file.name:
                        video_file = self.get_client().files.get(name=video_file.name)
                    time.sleep(2)

                if video_file.state and video_file.state.name == "FAILED":
                    log_error(f"Video file processing failed: {video_file.state.name}")
                    return None

            if video_file.uri:
                mime_type = f"video/{video.format}" if video.format else "video/mp4"
                return Part.from_uri(file_uri=video_file.uri, mime_type=mime_type)
            return None
        # Case 3: Video is a URL
        elif video.url is not None:
            mime_type = f"video/{video.format}" if video.format else "video/webm"
            return Part.from_uri(
                file_uri=video.url,
                mime_type=mime_type,
            )
        else:
            log_warning(f"Unknown video type: {type(video.content)}")
            return None

    def _format_file_for_message(self, file: File) -> Optional[Part]:
        # Case 1: File is a bytes object
        if file.content and isinstance(file.content, bytes):
            _mime = file.mime_type or mimetypes.guess_type(file.filename or "")[0] or "application/pdf"
            return Part.from_bytes(mime_type=_mime, data=file.content)

        # Case 2: File is a URL
        elif file.url is not None:
            # Case 2a: GCS URI (gs://) - pass directly to Gemini (supports up to 2GB)
            if file.url.startswith("gs://"):
                _mime = file.mime_type or mimetypes.guess_type(file.url)[0] or "application/pdf"
                return Part.from_uri(file_uri=file.url, mime_type=_mime)

            # Case 2b: HTTPS URL with known mime_type - pass directly to Gemini (supports up to 100MB)
            # URLs without mime_type fall through to Case 2c (download + detect) because
            # Gemini servers may not be able to access private/auth URLs directly.
            if file.url.startswith("https://") and file.mime_type:
                return Part.from_uri(file_uri=file.url, mime_type=file.mime_type)

            # Case 2c: Other URL schemes - download and detect
            url_content = file.file_url_content
            if url_content is not None:
                content, mime_type = url_content
                if content:
                    _mime = mime_type or mimetypes.guess_type(file.url)[0] or "application/pdf"
                    return Part.from_bytes(mime_type=_mime, data=content)
            log_warning(f"Failed to download file from {file.url}")
            return None

        # Case 3: File is a local file path
        elif file.filepath is not None:
            file_path = file.filepath if isinstance(file.filepath, Path) else Path(file.filepath)
            if file_path.exists() and file_path.is_file():
                if file_path.stat().st_size < 20 * 1024 * 1024:  # 20MB in bytes
                    file_content = file_path.read_bytes()
                    if file_content:
                        _mime = file.mime_type or mimetypes.guess_type(str(file_path))[0] or "application/pdf"
                        return Part.from_bytes(mime_type=_mime, data=file_content)
                    return None
                else:
                    clean_file_name = f"files/{file_path.stem.lower().replace('_', '')}"
                    remote_file = None
                    try:
                        if clean_file_name:
                            remote_file = self.get_client().files.get(name=clean_file_name)
                    except Exception as e:
                        log_warning(f"Error getting file {clean_file_name}: {e}")

                    if (
                        remote_file
                        and remote_file.state
                        and remote_file.state.name == "SUCCESS"
                        and remote_file.uri
                        and remote_file.mime_type
                    ):
                        file_uri: str = remote_file.uri
                        file_mime_type: str = remote_file.mime_type
                        return Part.from_uri(file_uri=file_uri, mime_type=file_mime_type)
            else:
                log_error(f"File {file_path} does not exist.")
            return None

        # Case 4: File is a Gemini File object
        elif isinstance(file.external, GeminiFile):
            if file.external.uri and file.external.mime_type:
                return Part.from_uri(file_uri=file.external.uri, mime_type=file.external.mime_type)
            return None
        return None

    def format_function_call_results(
        self,
        messages: List[Message],
        function_call_results: List[Message],
        compress_tool_results: bool = False,
        **kwargs,
    ) -> None:
        """
        Format function call results for Gemini.

        For combined messages:
        - content: list of ORIGINAL content (for preservation)
        - tool_calls[i]["content"]: compressed content if available (for API sending)

        This allows the message to be saved with both original and compressed versions.
        """
        combined_original_content: List = []
        combined_function_result: List = []
        tool_names: List[str] = []

        message_metrics = Metrics()

        if len(function_call_results) > 0:
            for idx, result in enumerate(function_call_results):
                combined_original_content.append(result.content)
                compressed_content = result.get_content(use_compressed_content=compress_tool_results)
                combined_function_result.append(
                    {"tool_call_id": result.tool_call_id, "tool_name": result.tool_name, "content": compressed_content}
                )
                if result.tool_name:
                    tool_names.append(result.tool_name)
                message_metrics += result.metrics

        tool_name = ", ".join(tool_names) if tool_names else None

        if combined_original_content:
            messages.append(
                Message(
                    role="tool",
                    content=combined_original_content,
                    tool_name=tool_name,
                    tool_calls=combined_function_result,
                    metrics=message_metrics,
                )
            )

    def _parse_provider_response(self, response: GenerateContentResponse, **kwargs) -> ModelResponse:
        """
        Parse the Gemini response into a ModelResponse.

        Args:
            response: Raw response from Gemini

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Get response message
        response_message = Content(role="model", parts=[])
        if response.candidates and len(response.candidates) > 0:
            candidate = response.candidates[0]

            # Raise if the request failed because of a malformed function call
            if hasattr(candidate, "finish_reason") and candidate.finish_reason:
                if candidate.finish_reason == GeminiFinishReason.MALFORMED_FUNCTION_CALL.value:
                    if self.retry_with_guidance:
                        raise RetryableModelProviderError(
                            retry_guidance_message=MALFORMED_FUNCTION_CALL_GUIDANCE,
                            original_error=f"Generation ended with finish reason: {candidate.finish_reason}",
                        )

            if candidate.content:
                response_message = candidate.content

        # Add role
        if response_message.role is not None:
            model_response.role = self.role_map[response_message.role]

        # Add content
        if response_message.parts is not None and len(response_message.parts) > 0:
            for part in response_message.parts:
                # Extract text if present
                if hasattr(part, "text") and part.text is not None:
                    text_content: Optional[str] = getattr(part, "text")
                    if isinstance(text_content, str):
                        # Check if this is a thought summary
                        if hasattr(part, "thought") and part.thought:
                            # Add all parts as single message
                            if model_response.reasoning_content is None:
                                model_response.reasoning_content = text_content
                            else:
                                model_response.reasoning_content += text_content
                        else:
                            if model_response.content is None:
                                model_response.content = text_content
                            else:
                                model_response.content += text_content
                    else:
                        content_str = str(text_content) if text_content is not None else ""
                        if hasattr(part, "thought") and part.thought:
                            # Add all parts as single message
                            if model_response.reasoning_content is None:
                                model_response.reasoning_content = content_str
                            else:
                                model_response.reasoning_content += content_str
                        else:
                            if model_response.content is None:
                                model_response.content = content_str
                            else:
                                model_response.content += content_str

                    # Capture thought signature for text parts
                    if hasattr(part, "thought_signature") and part.thought_signature:
                        if model_response.provider_data is None:
                            model_response.provider_data = {}
                        model_response.provider_data["thought_signature"] = base64.b64encode(
                            part.thought_signature
                        ).decode("ascii")

                if hasattr(part, "inline_data") and part.inline_data is not None:
                    # Handle audio responses (for TTS models)
                    if part.inline_data.mime_type and part.inline_data.mime_type.startswith("audio/"):
                        # Store raw bytes data
                        model_response.audio = Audio(
                            id=str(uuid4()),
                            content=part.inline_data.data,
                            mime_type=part.inline_data.mime_type,
                        )
                    # Image responses
                    else:
                        if model_response.images is None:
                            model_response.images = []
                        model_response.images.append(
                            Image(id=str(uuid4()), content=part.inline_data.data, mime_type=part.inline_data.mime_type)
                        )

                # Extract function call if present
                if hasattr(part, "function_call") and part.function_call is not None:
                    call_id = part.function_call.id if part.function_call.id else str(uuid4())
                    tool_call = {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": part.function_call.name,
                            "arguments": json.dumps(part.function_call.args)
                            if part.function_call.args is not None
                            else "",
                        },
                    }

                    # Capture thought signature for function calls
                    if hasattr(part, "thought_signature") and part.thought_signature:
                        tool_call["thought_signature"] = base64.b64encode(part.thought_signature).decode("ascii")

                    model_response.tool_calls.append(tool_call)

            citations = Citations()
            citations_raw = {}
            citations_urls = []
            web_search_queries: List[str] = []

            if response.candidates and response.candidates[0].grounding_metadata is not None:
                grounding_metadata: GroundingMetadata = response.candidates[0].grounding_metadata
                citations_raw["grounding_metadata"] = grounding_metadata.model_dump()

                chunks = grounding_metadata.grounding_chunks or []
                web_search_queries = grounding_metadata.web_search_queries or []
                for chunk in chunks:
                    if not chunk:
                        continue
                    web = chunk.web
                    if not web:
                        continue
                    uri = web.uri
                    title = web.title
                    if uri:
                        citations_urls.append(UrlCitation(url=uri, title=title))

            # Handle URLs from URL context tool
            if (
                response.candidates
                and hasattr(response.candidates[0], "url_context_metadata")
                and response.candidates[0].url_context_metadata is not None
            ):
                url_context_metadata = response.candidates[0].url_context_metadata
                citations_raw["url_context_metadata"] = url_context_metadata.model_dump()

                url_metadata_list = url_context_metadata.url_metadata or []
                for url_meta in url_metadata_list:
                    retrieved_url = url_meta.retrieved_url
                    status = "UNKNOWN"
                    if url_meta.url_retrieval_status:
                        status = url_meta.url_retrieval_status.value
                    if retrieved_url and status == "URL_RETRIEVAL_STATUS_SUCCESS":
                        # Avoid duplicate URLs
                        existing_urls = [citation.url for citation in citations_urls]
                        if retrieved_url not in existing_urls:
                            citations_urls.append(UrlCitation(url=retrieved_url, title=retrieved_url))

            if citations_raw:
                citations.raw = citations_raw
            if citations_urls:
                citations.urls = citations_urls
            if web_search_queries:
                citations.search_queries = web_search_queries

            if citations_raw or citations_urls:
                model_response.citations = citations

        # Extract usage metadata if present
        if hasattr(response, "usage_metadata") and response.usage_metadata is not None:
            model_response.response_usage = self._get_metrics(response.usage_metadata)

        # If we have no content but have a role, add a default empty content
        if model_response.role and model_response.content is None and not model_response.tool_calls:
            model_response.content = ""

        return model_response

    def _parse_provider_response_delta(self, response_delta: GenerateContentResponse, **kwargs) -> ModelResponse:
        model_response = ModelResponse()

        if response_delta.candidates and len(response_delta.candidates) > 0:
            candidate = response_delta.candidates[0]
            candidate_content = candidate.content

            # Raise if the request failed because of a malformed function call
            if hasattr(candidate, "finish_reason") and candidate.finish_reason:
                if candidate.finish_reason == GeminiFinishReason.MALFORMED_FUNCTION_CALL.value:
                    if self.retry_with_guidance:
                        raise RetryableModelProviderError(
                            retry_guidance_message=MALFORMED_FUNCTION_CALL_GUIDANCE,
                            original_error=f"Generation ended with finish reason: {candidate.finish_reason}",
                        )

            response_message: Content = Content(role="model", parts=[])
            if candidate_content is not None:
                response_message = candidate_content

            # Add role
            if response_message.role is not None:
                model_response.role = self.role_map[response_message.role]

            if response_message.parts is not None:
                for part in response_message.parts:
                    # Extract text if present
                    if hasattr(part, "text") and part.text is not None:
                        text_content = str(part.text) if part.text is not None else ""
                        # Check if this is a thought summary
                        if hasattr(part, "thought") and part.thought:
                            if model_response.reasoning_content is None:
                                model_response.reasoning_content = text_content
                            else:
                                model_response.reasoning_content += text_content
                        else:
                            if model_response.content is None:
                                model_response.content = text_content
                            else:
                                model_response.content += text_content

                        # Capture thought signature for text parts
                        if hasattr(part, "thought_signature") and part.thought_signature:
                            if model_response.provider_data is None:
                                model_response.provider_data = {}
                            model_response.provider_data["thought_signature"] = base64.b64encode(
                                part.thought_signature
                            ).decode("ascii")

                    if hasattr(part, "inline_data") and part.inline_data is not None:
                        # Audio responses
                        if part.inline_data.mime_type and part.inline_data.mime_type.startswith("audio/"):
                            # Store raw bytes audio data
                            model_response.audio = Audio(
                                id=str(uuid4()),
                                content=part.inline_data.data,
                                mime_type=part.inline_data.mime_type,
                            )
                        # Image responses
                        else:
                            if model_response.images is None:
                                model_response.images = []
                            model_response.images.append(
                                Image(
                                    id=str(uuid4()), content=part.inline_data.data, mime_type=part.inline_data.mime_type
                                )
                            )

                    # Extract function call if present
                    if hasattr(part, "function_call") and part.function_call is not None:
                        call_id = part.function_call.id if part.function_call.id else str(uuid4())
                        tool_call = {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": part.function_call.name,
                                "arguments": json.dumps(part.function_call.args)
                                if part.function_call.args is not None
                                else "",
                            },
                        }

                        # Capture thought signature for function calls
                        if hasattr(part, "thought_signature") and part.thought_signature:
                            tool_call["thought_signature"] = base64.b64encode(part.thought_signature).decode("ascii")

                        model_response.tool_calls.append(tool_call)

            citations = Citations()
            citations.raw = {}
            citations.urls = []

            if (
                hasattr(response_delta.candidates[0], "grounding_metadata")
                and response_delta.candidates[0].grounding_metadata is not None
            ):
                grounding_metadata = response_delta.candidates[0].grounding_metadata
                citations.raw["grounding_metadata"] = grounding_metadata.model_dump()
                citations.search_queries = grounding_metadata.web_search_queries or []
                # Extract url and title
                chunks = grounding_metadata.grounding_chunks or []
                for chunk in chunks:
                    if not chunk:
                        continue
                    web = chunk.web
                    if not web:
                        continue
                    uri = web.uri
                    title = web.title
                    if uri:
                        citations.urls.append(UrlCitation(url=uri, title=title))

            # Handle URLs from URL context tool
            if (
                hasattr(response_delta.candidates[0], "url_context_metadata")
                and response_delta.candidates[0].url_context_metadata is not None
            ):
                url_context_metadata = response_delta.candidates[0].url_context_metadata

                citations.raw["url_context_metadata"] = url_context_metadata.model_dump()

                url_metadata_list = url_context_metadata.url_metadata or []
                for url_meta in url_metadata_list:
                    retrieved_url = url_meta.retrieved_url
                    status = "UNKNOWN"
                    if url_meta.url_retrieval_status:
                        status = url_meta.url_retrieval_status.value
                    if retrieved_url and status == "URL_RETRIEVAL_STATUS_SUCCESS":
                        # Avoid duplicate URLs
                        existing_urls = [citation.url for citation in citations.urls]
                        if retrieved_url not in existing_urls:
                            citations.urls.append(UrlCitation(url=retrieved_url, title=retrieved_url))

            if citations.raw or citations.urls:
                model_response.citations = citations

            # Extract usage metadata if present
            if hasattr(response_delta, "usage_metadata") and response_delta.usage_metadata is not None:
                model_response.response_usage = self._get_metrics(response_delta.usage_metadata)

        return model_response

    def __deepcopy__(self, memo):
        """
        Creates a deep copy of the Gemini model instance but sets the client to None.

        This is useful when we need to copy the model configuration without duplicating
        the client connection.

        This overrides the base class implementation.
        """
        from copy import copy, deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        new_instance = cls.__new__(cls)

        # Update memo with the new instance to avoid circular references
        memo[id(self)] = new_instance

        # Deep copy all attributes except client and unpickleable attributes
        for key, value in self.__dict__.items():
            # Skip client and other unpickleable attributes
            if key in {"client", "response_format", "_tools", "_functions", "_function_call_stack"}:
                continue

            # Try deep copy first, fall back to shallow copy, then direct assignment
            try:
                setattr(new_instance, key, deepcopy(value, memo))
            except Exception:
                try:
                    setattr(new_instance, key, copy(value))
                except Exception:
                    setattr(new_instance, key, value)

        # Explicitly set client to None
        setattr(new_instance, "client", None)

        return new_instance

    def _get_metrics(self, response_usage: GenerateContentResponseUsageMetadata) -> Metrics:
        """
        Parse the given Google Gemini usage into an Agno Metrics object.

        Args:
            response_usage: Usage data from Google Gemini

        Returns:
            Metrics: Parsed metrics data
        """
        metrics = Metrics()

        metrics.input_tokens = response_usage.prompt_token_count or 0
        metrics.output_tokens = response_usage.candidates_token_count or 0
        if response_usage.thoughts_token_count is not None:
            metrics.output_tokens += response_usage.thoughts_token_count or 0
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        metrics.cache_read_tokens = response_usage.cached_content_token_count or 0

        if response_usage.traffic_type is not None:
            metrics.provider_metrics = {"traffic_type": response_usage.traffic_type}

        return metrics

    def create_file_search_store(self, display_name: Optional[str] = None) -> Any:
        """
        Create a new File Search store.

        Args:
            display_name: Optional display name for the store

        Returns:
            FileSearchStore: The created File Search store object
        """
        config: Dict[str, Any] = {}
        if display_name:
            config["display_name"] = display_name

        try:
            store = self.get_client().file_search_stores.create(config=config or None)  # type: ignore[arg-type]
            log_info(f"Created File Search store: {store.name}")
            return store
        except Exception as e:
            log_error(f"Error creating File Search store: {e}")
            raise

    async def async_create_file_search_store(self, display_name: Optional[str] = None) -> Any:
        """
        Args:
            display_name: Optional display name for the store

        Returns:
            FileSearchStore: The created File Search store object
        """
        config: Dict[str, Any] = {}
        if display_name:
            config["display_name"] = display_name

        try:
            store = await self.get_client().aio.file_search_stores.create(config=config or None)  # type: ignore[arg-type]
            log_info(f"Created File Search store: {store.name}")
            return store
        except Exception as e:
            log_error(f"Error creating File Search store: {e}")
            raise

    def list_file_search_stores(self, page_size: int = 100) -> List[Any]:
        """
        List all File Search stores.

        Args:
            page_size: Maximum number of stores to return per page

        Returns:
            List: List of FileSearchStore objects
        """
        try:
            stores = []
            for store in self.get_client().file_search_stores.list(config={"page_size": page_size}):
                stores.append(store)
            log_debug(f"Found {len(stores)} File Search stores")
            return stores
        except Exception as e:
            log_error(f"Error listing File Search stores: {e}")
            raise

    async def async_list_file_search_stores(self, page_size: int = 100) -> List[Any]:
        """
        Async version of list_file_search_stores.

        Args:
            page_size: Maximum number of stores to return per page

        Returns:
            List: List of FileSearchStore objects
        """
        try:
            stores = []
            async for store in await self.get_client().aio.file_search_stores.list(config={"page_size": page_size}):
                stores.append(store)
            log_debug(f"Found {len(stores)} File Search stores")
            return stores
        except Exception as e:
            log_error(f"Error listing File Search stores: {e}")
            raise

    def get_file_search_store(self, name: str) -> Any:
        """
        Get a specific File Search store by name.

        Args:
            name: The name of the store (e.g., 'fileSearchStores/my-store-123')

        Returns:
            FileSearchStore: The File Search store object
        """
        try:
            store = self.get_client().file_search_stores.get(name=name)
            log_debug(f"Retrieved File Search store: {name}")
            return store
        except Exception as e:
            log_error(f"Error getting File Search store {name}: {e}")
            raise

    async def async_get_file_search_store(self, name: str) -> Any:
        """
        Args:
            name: The name of the store

        Returns:
            FileSearchStore: The File Search store object
        """
        try:
            store = await self.get_client().aio.file_search_stores.get(name=name)
            log_debug(f"Retrieved File Search store: {name}")
            return store
        except Exception as e:
            log_error(f"Error getting File Search store {name}: {e}")
            raise

    def delete_file_search_store(self, name: str, force: bool = False) -> None:
        """
        Delete a File Search store.

        Args:
            name: The name of the store to delete
            force: If True, force delete even if store contains documents
        """
        try:
            self.get_client().file_search_stores.delete(name=name, config={"force": force})
            log_info(f"Deleted File Search store: {name}")
        except Exception as e:
            log_error(f"Error deleting File Search store {name}: {e}")
            raise

    async def async_delete_file_search_store(self, name: str, force: bool = True) -> None:
        """
        Async version of delete_file_search_store.

        Args:
            name: The name of the store to delete
            force: If True, force delete even if store contains documents
        """
        try:
            await self.get_client().aio.file_search_stores.delete(name=name, config={"force": force})
            log_info(f"Deleted File Search store: {name}")
        except Exception as e:
            log_error(f"Error deleting File Search store {name}: {e}")
            raise

    def wait_for_operation(self, operation: Operation, poll_interval: int = 5, max_wait: int = 600) -> Operation:
        """
        Wait for a long-running operation to complete.

        Args:
            operation: The operation object to wait for
            poll_interval: Seconds to wait between status checks
            max_wait: Maximum seconds to wait before timing out

        Returns:
            Operation: The completed operation object

        Raises:
            TimeoutError: If operation doesn't complete within max_wait seconds
        """
        elapsed = 0
        while not operation.done:
            if elapsed >= max_wait:
                raise TimeoutError(f"Operation timed out after {max_wait} seconds")
            time.sleep(poll_interval)
            elapsed += poll_interval
            operation = self.get_client().operations.get(operation)
            log_debug(f"Waiting for operation... ({elapsed}s elapsed)")

        log_info("Operation completed successfully")
        return operation

    async def async_wait_for_operation(
        self, operation: Operation, poll_interval: int = 5, max_wait: int = 600
    ) -> Operation:
        """
        Async version of wait_for_operation.

        Args:
            operation: The operation object to wait for
            poll_interval: Seconds to wait between status checks
            max_wait: Maximum seconds to wait before timing out

        Returns:
            Operation: The completed operation object
        """
        elapsed = 0
        while not operation.done:
            if elapsed >= max_wait:
                raise TimeoutError(f"Operation timed out after {max_wait} seconds")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            operation = await self.get_client().aio.operations.get(operation)
            log_debug(f"Waiting for operation... ({elapsed}s elapsed)")

        log_info("Operation completed successfully")
        return operation

    def upload_to_file_search_store(
        self,
        file_path: Union[str, Path],
        store_name: str,
        display_name: Optional[str] = None,
        chunking_config: Optional[Dict[str, Any]] = None,
        custom_metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """
        Upload a file directly to a File Search store.

        Args:
            file_path: Path to the file to upload
            store_name: Name of the File Search store
            display_name: Optional display name for the file (will be visible in citations)
            chunking_config: Optional chunking configuration
                Example: {
                    "white_space_config": {
                        "max_tokens_per_chunk": 200,
                        "max_overlap_tokens": 20
                    }
                }
            custom_metadata: Optional custom metadata as list of dicts
                Example: [
                    {"key": "author", "string_value": "John Doe"},
                    {"key": "year", "numeric_value": 2024}
                ]

        Returns:
            Operation: Long-running operation object. Use wait_for_operation() to wait for completion.
        """
        file_path = file_path if isinstance(file_path, Path) else Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        config: Dict[str, Any] = {}
        if display_name:
            config["display_name"] = display_name
        if chunking_config:
            config["chunking_config"] = chunking_config
        if custom_metadata:
            config["custom_metadata"] = custom_metadata

        try:
            log_info(f"Uploading file {file_path.name} to File Search store {store_name}")
            operation = self.get_client().file_search_stores.upload_to_file_search_store(
                file=file_path,
                file_search_store_name=store_name,
                config=config or None,  # type: ignore[arg-type]
            )
            log_info(f"Upload initiated for {file_path.name}")
            return operation
        except Exception as e:
            log_error(f"Error uploading file to File Search store: {e}")
            raise

    async def async_upload_to_file_search_store(
        self,
        file_path: Union[str, Path],
        store_name: str,
        display_name: Optional[str] = None,
        chunking_config: Optional[Dict[str, Any]] = None,
        custom_metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """
        Args:
            file_path: Path to the file to upload
            store_name: Name of the File Search store
            display_name: Optional display name for the file
            chunking_config: Optional chunking configuration
            custom_metadata: Optional custom metadata

        Returns:
            Operation: Long-running operation object
        """
        file_path = file_path if isinstance(file_path, Path) else Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        config: Dict[str, Any] = {}
        if display_name:
            config["display_name"] = display_name
        if chunking_config:
            config["chunking_config"] = chunking_config
        if custom_metadata:
            config["custom_metadata"] = custom_metadata

        try:
            log_info(f"Uploading file {file_path.name} to File Search store {store_name}")
            operation = await self.get_client().aio.file_search_stores.upload_to_file_search_store(
                file=file_path,
                file_search_store_name=store_name,
                config=config or None,  # type: ignore[arg-type]
            )
            log_info(f"Upload initiated for {file_path.name}")
            return operation
        except Exception as e:
            log_error(f"Error uploading file to File Search store: {e}")
            raise

    def import_file_to_store(
        self,
        file_name: str,
        store_name: str,
        chunking_config: Optional[Dict[str, Any]] = None,
        custom_metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """
        Import an existing uploaded file (via Files API) into a File Search store.

        Args:
            file_name: Name of the file already uploaded via Files API
            store_name: Name of the File Search store
            chunking_config: Optional chunking configuration
            custom_metadata: Optional custom metadata

        Returns:
            Operation: Long-running operation object. Use wait_for_operation() to wait for completion.
        """
        config: Dict[str, Any] = {}
        if chunking_config:
            config["chunking_config"] = chunking_config
        if custom_metadata:
            config["custom_metadata"] = custom_metadata

        try:
            log_info(f"Importing file {file_name} to File Search store {store_name}")
            operation = self.get_client().file_search_stores.import_file(
                file_search_store_name=store_name,
                file_name=file_name,
                config=config or None,  # type: ignore[arg-type]
            )
            log_info(f"Import initiated for {file_name}")
            return operation
        except Exception as e:
            log_error(f"Error importing file to File Search store: {e}")
            raise

    async def async_import_file_to_store(
        self,
        file_name: str,
        store_name: str,
        chunking_config: Optional[Dict[str, Any]] = None,
        custom_metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """
        Args:
            file_name: Name of the file already uploaded via Files API
            store_name: Name of the File Search store
            chunking_config: Optional chunking configuration
            custom_metadata: Optional custom metadata

        Returns:
            Operation: Long-running operation object
        """
        config: Dict[str, Any] = {}
        if chunking_config:
            config["chunking_config"] = chunking_config
        if custom_metadata:
            config["custom_metadata"] = custom_metadata

        try:
            log_info(f"Importing file {file_name} to File Search store {store_name}")
            operation = await self.get_client().aio.file_search_stores.import_file(
                file_search_store_name=store_name,
                file_name=file_name,
                config=config or None,  # type: ignore[arg-type]
            )
            log_info(f"Import initiated for {file_name}")
            return operation
        except Exception as e:
            log_error(f"Error importing file to File Search store: {e}")
            raise

    def list_documents(self, store_name: str, page_size: int = 20) -> List[Any]:
        """
        Args:
            store_name: Name of the File Search store
            page_size: Maximum number of documents to return per page

        Returns:
            List: List of document objects
        """
        try:
            documents = []
            for doc in self.get_client().file_search_stores.documents.list(
                parent=store_name, config={"page_size": page_size}
            ):
                documents.append(doc)
            log_debug(f"Found {len(documents)} documents in store {store_name}")
            return documents
        except Exception as e:
            log_error(f"Error listing documents in store {store_name}: {e}")
            raise

    async def async_list_documents(self, store_name: str, page_size: int = 20) -> List[Any]:
        """
        Async version of list_documents.

        Args:
            store_name: Name of the File Search store
            page_size: Maximum number of documents to return per page

        Returns:
            List: List of document objects
        """
        try:
            documents = []
            # Await the AsyncPager first, then iterate
            async for doc in await self.get_client().aio.file_search_stores.documents.list(
                parent=store_name, config={"page_size": page_size}
            ):
                documents.append(doc)
            log_debug(f"Found {len(documents)} documents in store {store_name}")
            return documents
        except Exception as e:
            log_error(f"Error listing documents in store {store_name}: {e}")
            raise

    def get_document(self, document_name: str) -> Any:
        """
        Get a specific document by name.

        Args:
            document_name: Full name of the document
                (e.g., 'fileSearchStores/store-123/documents/doc-456')

        Returns:
            Document object
        """
        try:
            doc = self.get_client().file_search_stores.documents.get(name=document_name)
            log_debug(f"Retrieved document: {document_name}")
            return doc
        except Exception as e:
            log_error(f"Error getting document {document_name}: {e}")
            raise

    async def async_get_document(self, document_name: str) -> Any:
        """
        Async version of get_document.

        Args:
            document_name: Full name of the document

        Returns:
            Document object
        """
        try:
            doc = await self.get_client().aio.file_search_stores.documents.get(name=document_name)
            log_debug(f"Retrieved document: {document_name}")
            return doc
        except Exception as e:
            log_error(f"Error getting document {document_name}: {e}")
            raise

    def delete_document(self, document_name: str) -> None:
        """
        Delete a document from a File Search store.

        Args:
            document_name: Full name of the document to delete

        Example:
            ```python
            model = Gemini(id="gemini-2.5-flash")
            model.delete_document("fileSearchStores/store-123/documents/doc-456")
            ```
        """
        try:
            self.get_client().file_search_stores.documents.delete(name=document_name)
            log_info(f"Deleted document: {document_name}")
        except Exception as e:
            log_error(f"Error deleting document {document_name}: {e}")
            raise

    async def async_delete_document(self, document_name: str) -> None:
        """
        Async version of delete_document.

        Args:
            document_name: Full name of the document to delete
        """
        try:
            await self.get_client().aio.file_search_stores.documents.delete(name=document_name)
            log_info(f"Deleted document: {document_name}")
        except Exception as e:
            log_error(f"Error deleting document {document_name}: {e}")
            raise
