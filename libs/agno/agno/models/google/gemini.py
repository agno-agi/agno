import json
import time
from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import Audio, File, ImageArtifact, Video
from agno.models.base import Model
from agno.models.message import Citations, Message, MessageMetrics, UrlCitation
from agno.models.response import ModelResponse
from agno.utils.gemini import convert_schema, format_function_definitions, format_image_for_message
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.models.schema_utils import get_response_schema_for_provider

try:
    from google import genai
    from google.genai import Client as GeminiClient
    from google.genai.errors import ClientError, ServerError
    from google.genai.types import (
        Content,
        DynamicRetrievalConfig,
        GenerateContentConfig,
        GenerateContentResponse,
        GenerateContentResponseUsageMetadata,
        GoogleSearch,
        GoogleSearchRetrieval,
        Part,
        Tool,
    )
    from google.genai.types import (
        File as GeminiFile,
    )
except ImportError:
    raise ImportError("`google-genai` not installed. Please install it using `pip install google-genai`")


@dataclass
class Gemini(Model):
    """
    Gemini model class for Google's Generative AI models.

    Vertex AI:
    - You will need Google Cloud credentials to use the Vertex AI API. Run `gcloud auth application-default login` to set credentials.
    - Set `vertexai` to `True` to use the Vertex AI API.
    - Set your `project_id` (or set `GOOGLE_CLOUD_PROJECT` environment variable) and `location` (optional).
    - Set `http_options` (optional) to configure the HTTP options.

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

    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_output_tokens: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    logprobs: Optional[bool] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    seed: Optional[int] = None
    response_modalities: Optional[list[str]] = None  # "Text" and/or "Image"
    speech_config: Optional[dict[str, Any]] = None
    cached_content: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
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
            client_params["project"] = self.project_id or getenv("GOOGLE_CLOUD_PROJECT")
            client_params["location"] = self.location or getenv("GOOGLE_CLOUD_LOCATION")

        client_params = {k: v for k, v in client_params.items() if v is not None}

        if self.client_params:
            client_params.update(self.client_params)

        self.client = genai.Client(**client_params)
        return self.client

    def _get_request_kwargs(
        self,
        system_message: Optional[str] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
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
            # Convert Pydantic model to JSON schema, then normalize for Gemini, then convert to Gemini schema format

            # Get the normalized schema for Gemini
            normalized_schema = get_response_schema_for_provider(response_format, "gemini")
            gemini_schema = convert_schema(normalized_schema)
            config["response_schema"] = gemini_schema

        if self.grounding and self.search:
            log_info("Both grounding and search are enabled. Grounding will take precedence.")
            self.search = False

        if self.grounding:
            log_info("Grounding enabled. External tools will be disabled.")
            config["tools"] = [
                Tool(
                    google_search=GoogleSearchRetrieval(
                        dynamic_retrieval_config=DynamicRetrievalConfig(
                            dynamic_threshold=self.grounding_dynamic_threshold
                        )
                    )
                ),
            ]

        elif self.search:
            log_info("Search enabled. External tools will be disabled.")
            config["tools"] = [Tool(google_search=GoogleSearch())]

        elif tools:
            config["tools"] = [format_function_definitions(tools)]

        config = {k: v for k, v in config.items() if v is not None}

        if config:
            request_params["config"] = GenerateContentConfig(**config)

        # Filter out None values
        if self.request_params:
            request_params.update(self.request_params)

        return request_params

    def invoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ):
        """
        Invokes the model with a list of messages and returns the response.
        """
        formatted_messages, system_message = self._format_messages(messages)
        request_kwargs = self._get_request_kwargs(system_message, response_format=response_format, tools=tools)
        try:
            return self.get_client().models.generate_content(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            error_message = str(e.response) if hasattr(e, "response") else str(e)
            raise ModelProviderError(
                message=error_message,
                status_code=e.code if hasattr(e, "code") and e.code is not None else 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ):
        """
        Invokes the model with a list of messages and returns the response as a stream.
        """
        formatted_messages, system_message = self._format_messages(messages)

        request_kwargs = self._get_request_kwargs(system_message, response_format=response_format, tools=tools)
        try:
            yield from self.get_client().models.generate_content_stream(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            raise ModelProviderError(
                message=str(e.response) if hasattr(e, "response") else str(e),
                status_code=e.code if hasattr(e, "code") and e.code is not None else 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ):
        """
        Invokes the model with a list of messages and returns the response.
        """
        formatted_messages, system_message = self._format_messages(messages)

        request_kwargs = self._get_request_kwargs(system_message, response_format=response_format, tools=tools)

        try:
            return await self.get_client().aio.models.generate_content(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            raise ModelProviderError(
                message=str(e.response) if hasattr(e, "response") else str(e),
                status_code=e.code if hasattr(e, "code") and e.code is not None else 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ):
        """
        Invokes the model with a list of messages and returns the response as a stream.
        """
        formatted_messages, system_message = self._format_messages(messages)

        request_kwargs = self._get_request_kwargs(system_message, response_format=response_format, tools=tools)

        try:
            async_stream = await self.get_client().aio.models.generate_content_stream(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
            async for chunk in async_stream:
                yield chunk
        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            raise ModelProviderError(
                message=str(e.response) if hasattr(e, "response") else str(e),
                status_code=e.code if hasattr(e, "code") and e.code is not None else 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def _format_messages(self, messages: List[Message]):
        """
        Converts a list of Message objects to the Gemini-compatible format.

        Args:
            messages (List[Message]): The list of messages to convert.
        """
        formatted_messages: List = []
        file_content: Optional[Union[GeminiFile, Part]] = None
        system_message = None
        for message in messages:
            role = message.role
            if role in ["system", "developer"]:
                system_message = message.content
                continue

            # Set the role for the message according to Gemini's requirements
            role = self.reverse_role_map.get(role, role)

            # Add content to the message for the model
            content = message.content
            # Initialize message_parts to be used for Gemini
            message_parts: List[Any] = []

            # Function calls
            if (not content or role == "model") and message.tool_calls is not None and len(message.tool_calls) > 0:
                for tool_call in message.tool_calls:
                    message_parts.append(
                        Part.from_function_call(
                            name=tool_call["function"]["name"],
                            args=json.loads(tool_call["function"]["arguments"]),
                        )
                    )
            # Function results
            elif message.tool_calls is not None and len(message.tool_calls) > 0:
                for tool_call in message.tool_calls:
                    message_parts.append(
                        Part.from_function_response(
                            name=tool_call["tool_name"], response={"result": tool_call["content"]}
                        )
                    )
            # Regular text content
            else:
                if isinstance(content, str):
                    message_parts = [Part.from_text(text=content)]

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
                            formatted_messages.append(file_content)

            final_message = Content(role=role, parts=message_parts)
            formatted_messages.append(final_message)

            if isinstance(file_content, GeminiFile):
                formatted_messages.insert(0, file_content)

        return formatted_messages, system_message

    def _format_audio_for_message(self, audio: Audio) -> Optional[Union[Part, GeminiFile]]:
        # Case 1: Audio is a bytes object
        if audio.content and isinstance(audio.content, bytes):
            mime_type = f"audio/{audio.format}" if audio.format else "audio/mp3"
            return Part.from_bytes(mime_type=mime_type, data=audio.content)

        # Case 2: Audio is an url
        elif audio.url is not None and audio.audio_url_content is not None:
            mime_type = f"audio/{audio.format}" if audio.format else "audio/mp3"
            return Part.from_bytes(mime_type=mime_type, data=audio.audio_url_content)

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
        if file.content and isinstance(file.content, bytes) and file.mime_type:
            return Part.from_bytes(mime_type=file.mime_type, data=file.content)

        # Case 2: File is a URL
        elif file.url is not None:
            url_content = file.file_url_content
            if url_content is not None:
                content, mime_type = url_content
                if mime_type and content:
                    return Part.from_bytes(mime_type=mime_type, data=content)
            log_warning(f"Failed to download file from {file.url}")
            return None

        # Case 3: File is a local file path
        elif file.filepath is not None:
            file_path = file.filepath if isinstance(file.filepath, Path) else Path(file.filepath)
            if file_path.exists() and file_path.is_file():
                if file_path.stat().st_size < 20 * 1024 * 1024:  # 20MB in bytes
                    if file.mime_type:
                        file_content = file_path.read_bytes()
                        if file_content:
                            return Part.from_bytes(mime_type=file.mime_type, data=file_content)
                    else:
                        import mimetypes

                        mime_type_guess = mimetypes.guess_type(file_path)[0]
                        if mime_type_guess is not None:
                            file_content = file_path.read_bytes()
                            if file_content:
                                mime_type_str: str = str(mime_type_guess)
                                return Part.from_bytes(mime_type=mime_type_str, data=file_content)
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
        self, messages: List[Message], function_call_results: List[Message], **kwargs
    ) -> None:
        """
        Format function call results.
        """
        combined_content: List = []
        combined_function_result: List = []
        message_metrics = MessageMetrics()
        if len(function_call_results) > 0:
            for result in function_call_results:
                combined_content.append(result.content)
                combined_function_result.append({"tool_name": result.tool_name, "content": result.content})
                message_metrics += result.metrics

        if combined_content:
            messages.append(
                Message(
                    role="tool", content=combined_content, tool_calls=combined_function_result, metrics=message_metrics
                )
            )

    def parse_provider_response(self, response: GenerateContentResponse, **kwargs) -> ModelResponse:
        """
        Parse the OpenAI response into a ModelResponse.

        Args:
            response: Raw response from OpenAI

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Get response message
        response_message = Content(role="model", parts=[])
        if response.candidates and response.candidates[0].content:
            response_message = response.candidates[0].content

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
                        model_response.content = text_content
                    else:
                        model_response.content = str(text_content) if text_content is not None else ""

                if hasattr(part, "inline_data") and part.inline_data is not None:
                    model_response.image = ImageArtifact(
                        id=str(uuid4()), content=part.inline_data.data, mime_type=part.inline_data.mime_type
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

                    model_response.tool_calls.append(tool_call)

            if response.candidates and response.candidates[0].grounding_metadata is not None:
                citations = Citations()
                grounding_metadata = response.candidates[0].grounding_metadata.model_dump()
                citations.raw = grounding_metadata

                # Extract url and title
                chunks = grounding_metadata.pop("grounding_chunks", None) or []
                citation_pairs = [
                    (chunk.get("web", {}).get("uri"), chunk.get("web", {}).get("title"))
                    for chunk in chunks
                    if chunk.get("web", {}).get("uri")
                ]

                # Create citation objects from filtered pairs
                citations.urls = [UrlCitation(url=url, title=title) for url, title in citation_pairs]

                model_response.citations = citations

        # Extract usage metadata if present
        if hasattr(response, "usage_metadata") and response.usage_metadata is not None:
            usage: GenerateContentResponseUsageMetadata = response.usage_metadata
            model_response.response_usage = {
                "input_tokens": usage.prompt_token_count or 0,
                "output_tokens": usage.candidates_token_count or 0,
                "total_tokens": usage.total_token_count or 0,
                "cached_tokens": usage.cached_content_token_count or 0,
            }

        # If we have no content but have a role, add a default empty content
        if model_response.role and model_response.content is None and not model_response.tool_calls:
            model_response.content = ""

        return model_response

    def parse_provider_response_delta(self, response_delta: GenerateContentResponse) -> ModelResponse:
        model_response = ModelResponse()

        if response_delta.candidates and len(response_delta.candidates) > 0:
            candidate_content = response_delta.candidates[0].content
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
                        model_response.content = str(part.text) if part.text is not None else ""

                    if hasattr(part, "inline_data") and part.inline_data is not None:
                        model_response.image = ImageArtifact(
                            id=str(uuid4()), content=part.inline_data.data, mime_type=part.inline_data.mime_type
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

                        model_response.tool_calls.append(tool_call)

            if response_delta.candidates[0].grounding_metadata is not None:
                citations = Citations()
                grounding_metadata = response_delta.candidates[0].grounding_metadata.model_dump()
                citations.raw = grounding_metadata

                # Extract url and title
                chunks = grounding_metadata.pop("grounding_chunks", None) or []
                citation_pairs = [
                    (chunk.get("web", {}).get("uri"), chunk.get("web", {}).get("title"))
                    for chunk in chunks
                    if chunk.get("web", {}).get("uri")
                ]

                # Create citation objects from filtered pairs
                citations.urls = [UrlCitation(url=url, title=title) for url, title in citation_pairs]

                model_response.citations = citations

            # Extract usage metadata if present
            if hasattr(response_delta, "usage_metadata") and response_delta.usage_metadata is not None:
                usage: GenerateContentResponseUsageMetadata = response_delta.usage_metadata
                model_response.response_usage = {
                    "input_tokens": usage.prompt_token_count or 0,
                    "output_tokens": usage.candidates_token_count or 0,
                    "total_tokens": usage.total_token_count or 0,
                    "cached_tokens": usage.cached_content_token_count or 0,
                }

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
