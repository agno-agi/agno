import json
import time
import traceback
from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import Audio, File, ImageArtifact, Video
from agno.models.base import Model
from agno.models.message import Citations, Message, MessageMetrics, UrlCitation
from agno.models.response import ModelResponse
from agno.utils.gemini import format_function_definitions, format_image_for_message
from agno.utils.log import log_error, log_info, log_warning

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

    id: str = "gemini-2.0-flash-exp"
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

    def _get_request_kwargs(self, system_message: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns the request keyword arguments for the GenerativeModel client.

        Returns:
            Dict[str, Any]: The request keyword arguments.
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
            }
        )

        if system_message is not None:
            config["system_instruction"] = system_message  # type: ignore

        if (
            self.response_format is not None
            and isinstance(self.response_format, type)
            and issubclass(self.response_format, BaseModel)
        ):
            config["response_mime_type"] = "application/json"  # type: ignore
            config["response_schema"] = self.response_format

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

        elif self._tools:
            config["tools"] = [format_function_definitions(self._tools)]

        config = {k: v for k, v in config.items() if v is not None}

        if config:
            request_params["config"] = GenerateContentConfig(**config)

        # Filter out None values
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def invoke(self, messages: List[Message]):
        """
        Invokes the model with a list of messages and returns the response.

        Args:
            messages (List[Message]): The list of messages to send to the model.

        Returns:
            GenerateContentResponse: The response from the model.
        """
        formatted_messages, system_message = self._format_messages(messages)
        request_kwargs = self._get_request_kwargs(system_message)
        try:
            return self.get_client().models.generate_content(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            raise ModelProviderError(
                message=e.response, status_code=e.code, model_name=self.name, model_id=self.id
            ) from e
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(self, messages: List[Message]):
        """
        Invokes the model with a list of messages and returns the response as a stream.

        Args:
            messages (List[Message]): The list of messages to send to the model.

        Returns:
            Iterator[GenerateContentResponse]: The response from the model as a stream.
        """
        formatted_messages, system_message = self._format_messages(messages)

        request_kwargs = self._get_request_kwargs(system_message)
        try:
            yield from self.get_client().models.generate_content_stream(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            raise ModelProviderError(
                message=e.response, status_code=e.code, model_name=self.name, model_id=self.id
            ) from e
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(self, messages: List[Message]):
        """
        Invokes the model with a list of messages and returns the response.
        """
        formatted_messages, system_message = self._format_messages(messages)

        request_kwargs = self._get_request_kwargs(system_message)

        try:
            return await self.get_client().aio.models.generate_content(
                model=self.id,
                contents=formatted_messages,
                **request_kwargs,
            )
        except (ClientError, ServerError) as e:
            log_error(f"Error from Gemini API: {e}")
            raise ModelProviderError(
                message=e.response, status_code=e.code, model_name=self.name, model_id=self.id
            ) from e
        except Exception as e:
            log_error(f"Unknown error from Gemini API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(self, messages: List[Message]):
        """
        Invokes the model with a list of messages and returns the response as a stream.
        """
        formatted_messages, system_message = self._format_messages(messages)

        request_kwargs = self._get_request_kwargs(system_message)

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
                message=e.response, status_code=e.code, model_name=self.name, model_id=self.id
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
                                # Google recommends that if using a single image, place the text prompt after the image.
                                message_parts.insert(
                                    0, Part.from_uri(file_uri=video.content.uri, mime_type=video.content.mime_type)
                                )
                            else:
                                video_file = self._format_video_for_message(video)

                                # Google recommends that if using a single video, place the text prompt after the video.
                                if video_file is not None:
                                    message_parts.insert(0, video_file)  # type: ignore
                    except Exception as e:
                        traceback.print_exc()
                        log_warning(f"Failed to load video from {message.videos}: {e}")
                        continue

                # Add audio to the message for the model
                if message.audio is not None:
                    try:
                        for audio_snippet in message.audio:
                            if audio_snippet.content is not None and isinstance(audio_snippet.content, GeminiFile):
                                # Google recommends that if using a single image, place the text prompt after the image.
                                message_parts.insert(
                                    0,
                                    Part.from_uri(
                                        file_uri=audio_snippet.content.uri, mime_type=audio_snippet.content.mime_type
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
                        if file_content:
                            message_parts.append(file_content)

            final_message = Content(role=role, parts=message_parts)
            formatted_messages.append(final_message)
        return formatted_messages, system_message

    def _format_audio_for_message(self, audio: Audio) -> Optional[Union[Part, GeminiFile]]:
        # Case 1: Audio is a bytes object
        if audio.content and isinstance(audio.content, bytes):
            return Part.from_bytes(
                mime_type=f"audio/{audio.format}" if audio.format else "audio/mp3", data=audio.content
            )

        # Case 2: Audio is an url
        elif audio.url is not None:
            return Part.from_bytes(
                mime_type=f"audio/{audio.format}" if audio.format else "audio/mp3", data=audio.audio_url_content
            )

        # Case 3: Audio is a local file path
        elif audio.filepath is not None:
            audio_path = audio.filepath if isinstance(audio.filepath, Path) else Path(audio.filepath)

            remote_file_name = f"files/{audio_path.stem.lower().replace('_', '')}"
            # Check if video is already uploaded
            existing_audio_upload = None
            try:
                existing_audio_upload = self.get_client().files.get(name=remote_file_name)
            except Exception as e:
                log_warning(f"Error getting file {remote_file_name}: {e}")
                pass

            if existing_audio_upload:
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
                    raise Exception(f"Audio file {audio_path} does not exist.")

                # Check whether the file is ready to be used.
                while audio_file.state.name == "PROCESSING":
                    time.sleep(2)
                    audio_file = self.get_client().files.get(name=audio_file.name)

                if audio_file.state.name == "FAILED":
                    raise ValueError(audio_file.state.name)
            return Part.from_uri(
                file_uri=audio_file.uri, mime_type=f"audio/{audio.format}" if audio.format else "audio/mp3"
            )
        else:
            log_warning(f"Unknown audio type: {type(audio.content)}")
            return None

    def _format_video_for_message(self, video: Video) -> Optional[GeminiFile]:
        # Case 1: Video is a bytes object
        if video.content and isinstance(video.content, bytes):
            return Part.from_bytes(
                mime_type=f"video/{video.format}" if video.format else "video/mp4", data=video.content
            )
        # Case 2: Video is stored locally
        elif video.filepath is not None:
            video_path = video.filepath if isinstance(video.filepath, Path) else Path(video.filepath)

            remote_file_name = f"files/{video_path.stem.lower().replace('_', '')}"
            # Check if video is already uploaded
            existing_video_upload = None
            try:
                existing_video_upload = self.get_client().files.get(name=remote_file_name)
            except Exception as e:
                log_warning(f"Error getting file {remote_file_name}: {e}")
                pass

            if existing_video_upload:
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
                    raise Exception(f"Video file {video_path} does not exist.")

                # Check whether the file is ready to be used.
                while video_file.state.name == "PROCESSING":
                    time.sleep(2)
                    video_file = self.get_client().files.get(name=video_file.name)

                if video_file.state.name == "FAILED":
                    raise ValueError(video_file.state.name)

            return Part.from_uri(
                file_uri=video_file.uri, mime_type=f"video/{video.format}" if video.format else "video/mp4"
            )
        else:
            log_warning(f"Unknown video type: {type(video.content)}")
            return None

    def _format_file_for_message(self, file: File) -> Optional[Part]:
        # Case 1: File is a bytes object
        if file.content and isinstance(file.content, bytes):
            return Part.from_bytes(mime_type=file.mime_type, data=file.content)

        # Case 2: File is a URL
        elif file.url is not None:
            url_content = file.file_url_content
            if url_content is not None:
                content, mime_type = url_content
                return Part.from_bytes(mime_type=mime_type, data=content)
            else:
                log_warning(f"Failed to download file from {file.url}")
                return None

        # Case 3: File is a local file path
        elif file.filepath is not None:
            file_path = file.filepath if isinstance(file.filepath, Path) else Path(file.filepath)
            if file_path.exists() and file_path.is_file():
                if file_path.stat().st_size < 20 * 1024 * 1024:  # 20MB in bytes
                    if file.mime_type is not None:
                        return Part.from_bytes(mime_type=file.mime_type, data=file_path.read_bytes())
                    else:
                        import mimetypes

                        return Part.from_bytes(
                            mime_type=mimetypes.guess_type(file_path)[0], data=file_path.read_bytes()
                        )
                else:
                    file_upload = self.get_client().files.upload(
                        file=file_path,
                    )
                    # Check whether the file is ready to be used.
                    while file_upload.state.name == "PROCESSING":
                        time.sleep(2)
                        file_upload = self.get_client().files.get(name=file_upload.name)
                    if file_upload.state.name == "FAILED":
                        raise ValueError(file_upload.state.name)
                    return Part.from_uri(file_uri=file_upload.uri, mime_type=file_upload.mime_type)
            else:
                log_error(f"File {file_path} does not exist.")

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

    def parse_provider_response(self, response: GenerateContentResponse) -> ModelResponse:
        """
        Parse the OpenAI response into a ModelResponse.

        Args:
            response: Raw response from OpenAI

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Get response message
        if response.candidates is not None:
            response_message: Content = response.candidates[0].content

            # Add role
            if response_message.role is not None:
                model_response.role = self.role_map[response_message.role]

            # Add content
            if response_message.parts is not None:
                for part in response_message.parts:
                    # Extract text if present
                    if hasattr(part, "text") and part.text is not None:
                        model_response.content = part.text

                    if hasattr(part, "inline_data") and part.inline_data is not None:
                        model_response.image = ImageArtifact(
                            id=str(uuid4()), content=part.inline_data.data, mime_type=part.inline_data.mime_type
                        )

                    # Extract function call if present
                    if hasattr(part, "function_call") and part.function_call is not None:
                        tool_call = {
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
            }

        return model_response

    def parse_provider_response_delta(self, response_delta: GenerateContentResponse) -> ModelResponse:
        model_response = ModelResponse()

        response_message: Content = response_delta.candidates[0].content

        # Add role
        if response_message.role is not None:
            model_response.role = self.role_map[response_message.role]

        if response_message.parts is not None:
            for part in response_message.parts:
                # Extract text if present
                if hasattr(part, "text") and part.text is not None:
                    model_response.content = part.text

                if hasattr(part, "inline_data") and part.inline_data is not None:
                    model_response.image = ImageArtifact(
                        id=str(uuid4()), content=part.inline_data.data, mime_type=part.inline_data.mime_type
                    )

                # Extract function call if present
                if hasattr(part, "function_call") and part.function_call is not None:
                    tool_call = {
                        "type": "function",
                        "function": {
                            "name": part.function_call.name,
                            "arguments": json.dumps(part.function_call.args)
                            if part.function_call.args is not None
                            else "",
                        },
                    }

                    model_response.tool_calls.append(tool_call)

        if response_delta.candidates and response_delta.candidates[0].grounding_metadata is not None:
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
            }

        return model_response
