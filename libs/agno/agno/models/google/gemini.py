import json
import time
import traceback
from dataclasses import dataclass, field
from os import getenv
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

from agno.media import Audio, Image, Video
from agno.models.base import Metrics, Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools import Function, Toolkit
from agno.utils.log import logger

try:
    import google.generativeai as genai
    from google.ai.generativelanguage_v1beta.types import (
        FunctionCall as GeminiFunctionCall,
    )
    from google.ai.generativelanguage_v1beta.types import (
        FunctionResponse as GeminiFunctionResponse,
    )
    from google.ai.generativelanguage_v1beta.types import (
        Part,
    )
    from google.ai.generativelanguage_v1beta.types.generative_service import (
        GenerateContentResponse as ResultGenerateContentResponse,
    )
    from google.api_core.exceptions import PermissionDenied
    from google.generativeai import GenerativeModel
    from google.generativeai.types import file_types
    from google.generativeai.types.content_types import FunctionDeclaration
    from google.generativeai.types.content_types import Tool as GeminiTool
    from google.generativeai.types.generation_types import GenerateContentResponse
    from google.protobuf.struct_pb2 import Struct
except (ModuleNotFoundError, ImportError):
    raise ImportError("`google-generativeai` not installed. Please install it using `pip install google-generativeai`")


@dataclass
class MessageData:
    response_content: str = ""
    response_block: Optional[GenerateContentResponse] = None
    response_role: Optional[str] = None
    response_parts: Optional[List] = None
    valid_response_parts: Optional[List] = None
    response_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    response_usage: Optional[ResultGenerateContentResponse] = None


def _format_image_for_message(image: Image) -> Optional[Dict[str, Any]]:
    # Case 1: Image is a URL
    # Download the image from the URL and add it as base64 encoded data
    if image.url is not None and image.image_url_content is not None:
        try:
            import base64

            content_bytes = image.image_url_content
            image_data = {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(content_bytes).decode("utf-8"),
            }
            return image_data
        except Exception as e:
            logger.warning(f"Failed to download image from {image}: {e}")
            return None
    # Case 2: Image is a local path
    # Open the image file and add it as base64 encoded data
    elif image.filepath is not None:
        try:
            import PIL.Image
        except ImportError:
            logger.error("`PIL.Image not installed. Please install it using 'pip install pillow'`")
            raise

        try:
            image_path = Path(image.filepath)
            if image_path.exists() and image_path.is_file():
                image_data = PIL.Image.open(image_path)  # type: ignore
            else:
                logger.error(f"Image file {image_path} does not exist.")
                raise
            return image_data  # type: ignore
        except Exception as e:
            logger.warning(f"Failed to load image from {image.filepath}: {e}")
            return None

    # Case 3: Image is a bytes object
    # Add it as base64 encoded data
    elif image.content is not None and isinstance(image.content, bytes):
        import base64

        image_data = {"mime_type": "image/jpeg", "data": base64.b64encode(image.content).decode("utf-8")}
        return image_data
    else:
        logger.warning(f"Unknown image type: {type(image)}")
        return None


def _format_audio_for_message(audio: Audio) -> Optional[Union[Dict[str, Any], file_types.File]]:
    if audio.content and isinstance(audio.content, bytes):
        audio_content = {"mime_type": "audio/mp3", "data": audio.content}
        return audio_content

    elif audio.filepath is not None:
        audio_path = audio.filepath if isinstance(audio.filepath, Path) else Path(audio.filepath)

        remote_file_name = f"files/{audio_path.stem.lower()}"
        # Check if video is already uploaded
        existing_audio_upload = None
        try:
            existing_audio_upload = genai.get_file(remote_file_name)
        except PermissionDenied:
            pass

        if existing_audio_upload:
            audio_file = existing_audio_upload
        else:
            # Upload the video file to the Gemini API
            if audio_path.exists() and audio_path.is_file():
                audio_file = genai.upload_file(path=audio_path, name=remote_file_name, display_name=audio_path.stem)
            else:
                logger.error(f"Audio file {audio_path} does not exist.")
                raise Exception(f"Audio file {audio_path} does not exist.")

            # Check whether the file is ready to be used.
            while audio_file.state.name == "PROCESSING":
                time.sleep(2)
                audio_file = genai.get_file(audio_file.name)

            if audio_file.state.name == "FAILED":
                raise ValueError(audio_file.state.name)
        return audio_file
    else:
        logger.warning(f"Unknown audio type: {type(audio.content)}")
        return None


def _format_video_for_message(video: Video) -> Optional[file_types.File]:
    # If video is stored locally
    if video.filepath is not None:
        video_path = video.filepath if isinstance(video.filepath, Path) else Path(video.filepath)

        remote_file_name = f"files/{video_path.stem.lower()}"
        # Check if video is already uploaded
        existing_video_upload = None
        try:
            existing_video_upload = genai.get_file(remote_file_name)
        except PermissionDenied:
            pass

        if existing_video_upload:
            video_file = existing_video_upload
        else:
            # Upload the video file to the Gemini API
            if video_path.exists() and video_path.is_file():
                video_file = genai.upload_file(path=video_path, name=remote_file_name, display_name=video_path.stem)
            else:
                logger.error(f"Video file {video_path} does not exist.")
                raise Exception(f"Video file {video_path} does not exist.")

            # Check whether the file is ready to be used.
            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = genai.get_file(video_file.name)

            if video_file.state.name == "FAILED":
                raise ValueError(video_file.state.name)

        return video_file
    else:
        logger.warning(f"Unknown video type: {type(video.content)}")
        return None


def _format_messages(messages: List[Message]) -> List[Dict[str, Any]]:
    """
    Converts a list of Message objects to the Gemini-compatible format.

    Args:
        messages (List[Message]): The list of messages to convert.

    Returns:
        List[Dict[str, Any]]: The formatted_messages list of messages.
    """
    formatted_messages: List = []
    for message in messages:
        message_for_model: Dict[str, Any] = {}

        # Add role to the message for the model
        role = (
            "model" if message.role in ["system", "developer"] else "user" if message.role == "tool" else message.role
        )
        message_for_model["role"] = role

        # Add content to the message for the model
        content = message.content
        # Initialize message_parts to be used for Gemini
        message_parts: List[Any] = []

        # Function calls
        if (not content or message.role == "model") and message.tool_calls:
            for tool_call in message.tool_calls:
                message_parts.append(
                    Part(
                        function_call=GeminiFunctionCall(
                            name=tool_call["function"]["name"],
                            args=json.loads(tool_call["function"]["arguments"]),
                        )
                    )
                )
        # Function results
        elif message.role == "tool" and hasattr(message, "combined_function_result"):
            s = Struct()
            for combined_result in message.combined_function_result:
                function_name = combined_result[0]
                function_response = combined_result[1]
                s.update({"result": [function_response]})
                message_parts.append(Part(function_response=GeminiFunctionResponse(name=function_name, response=s)))
        # Normal content
        else:
            if isinstance(content, str):
                message_parts = [content]
            elif isinstance(content, list):
                message_parts = content
            else:
                message_parts = [" "]

        if message.role == "user":
            # Add images to the message for the model
            if message.images is not None:
                for image in message.images:
                    if image.content is not None and isinstance(image.content, file_types.File):
                        # Google recommends that if using a single image, place the text prompt after the image.
                        message_parts.insert(0, image.content)
                    else:
                        image_content = _format_image_for_message(image)
                        if image_content:
                            message_parts.append(image_content)

            # Add videos to the message for the model
            if message.videos is not None:
                try:
                    for video in message.videos:
                        # Case 1: Video is a file_types.File object (Recommended)
                        # Add it as a File object
                        if video.content is not None and isinstance(video.content, file_types.File):
                            # Google recommends that if using a single image, place the text prompt after the image.
                            message_parts.insert(0, video.content)
                        else:
                            video_file = _format_video_for_message(video)

                            # Google recommends that if using a single video, place the text prompt after the video.
                            if video_file is not None:
                                message_parts.insert(0, video_file)  # type: ignore
                except Exception as e:
                    traceback.print_exc()
                    logger.warning(f"Failed to load video from {message.videos}: {e}")
                    continue

            # Add audio to the message for the model
            if message.audio is not None:
                try:
                    for audio_snippet in message.audio:
                        if audio_snippet.content is not None and isinstance(audio_snippet.content, file_types.File):
                            # Google recommends that if using a single image, place the text prompt after the image.
                            message_parts.insert(0, audio_snippet.content)
                        else:
                            audio_content = _format_audio_for_message(audio_snippet)
                            if audio_content:
                                message_parts.append(audio_content)
                except Exception as e:
                    logger.warning(f"Failed to load audio from {message.audio}: {e}")
                    continue

        message_for_model["parts"] = message_parts
        formatted_messages.append(message_for_model)
    return formatted_messages


def _format_functions(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts function parameters to a Gemini-compatible format.

    Args:
        params (Dict[str, Any]): The original parameters dictionary.

    Returns:
        Dict[str, Any]: The converted parameters dictionary compatible with Gemini.
    """
    formatted_params = {}

    for key, value in params.items():
        if key == "properties" and isinstance(value, dict):
            converted_properties = {}
            for prop_key, prop_value in value.items():
                property_type = prop_value.get("type")
                if property_type == "array":
                    converted_properties[prop_key] = prop_value
                    continue
                if isinstance(property_type, list):
                    # Create a copy to avoid modifying the original list
                    non_null_types = [t for t in property_type if t != "null"]
                    if non_null_types:
                        # Use the first non-null type
                        converted_type = non_null_types[0]
                        if converted_type == "array":
                            prop_value["type"] = converted_type
                            converted_properties[prop_key] = prop_value
                            continue
                    else:
                        # Default type if all types are 'null'
                        converted_type = "string"
                else:
                    converted_type = property_type

                converted_properties[prop_key] = {"type": converted_type}
            formatted_params[key] = converted_properties
        else:
            formatted_params[key] = value

    return formatted_params


def _build_function_declaration(func: Function) -> FunctionDeclaration:
    """
    Builds the function declaration for Gemini tool calling.

    Args:
        func: An instance of the function.

    Returns:
        FunctionDeclaration: The formatted function declaration.
    """
    formatted_params = _format_functions(func.parameters)
    if "properties" in formatted_params and formatted_params["properties"]:
        # We have parameters to add
        return FunctionDeclaration(
            name=func.name,
            description=func.description,
            parameters=formatted_params,
        )
    else:
        return FunctionDeclaration(
            name=func.name,
            description=func.description,
        )


@dataclass
class Gemini(Model):
    """
    Gemini model class for Google's Generative AI models.

    Based on https://ai.google.dev/gemini-api/docs/function-calling

    Attributes:
        id (str): Model ID. Default is `gemini-2.0-flash-exp`.
        name (str): The name of this chat model instance. Default is `Gemini`.
        provider (str): Model provider. Default is `Google`.
        function_declarations (List[FunctionDeclaration]): List of function declarations.
        generation_config (Any): Generation configuration.
        safety_settings (Any): Safety settings.
        generative_model_kwargs (Dict[str, Any]): Generative model keyword arguments.
        api_key (str): API key.
        client (GenerativeModel): Generative model client.
    """

    id: str = "gemini-2.0-flash-exp"
    name: str = "Gemini"
    provider: str = "Google"

    # Request parameters
    function_declarations: Optional[List[FunctionDeclaration]] = None
    generation_config: Optional[Any] = None
    safety_settings: Optional[Any] = None
    generative_model_kwargs: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    client_params: Optional[Dict[str, Any]] = None

    # Gemini client
    client: Optional[GenerativeModel] = None

    def get_client(self) -> GenerativeModel:
        """
        Returns an instance of the GenerativeModel client.

        Returns:
            GenerativeModel: The GenerativeModel client.
        """
        if self.client:
            return self.client

        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.error("GOOGLE_API_KEY not set. Please set the GOOGLE_API_KEY environment variable.")
        client_params["api_key"] = self.api_key

        if self.client_params:
            client_params.update(self.client_params)
        genai.configure(**client_params)

        self.client = genai.GenerativeModel(model_name=self.id, **self.request_kwargs)
        return self.client

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns the request keyword arguments for the GenerativeModel client.

        Returns:
            Dict[str, Any]: The request keyword arguments.
        """
        request_params: Dict[str, Any] = {}
        if self.generation_config:
            request_params["generation_config"] = self.generation_config
        if self.safety_settings:
            request_params["safety_settings"] = self.safety_settings
        if self.generative_model_kwargs:
            request_params.update(self.generative_model_kwargs)
        if self.function_declarations:
            request_params["tools"] = [GeminiTool(function_declarations=self.function_declarations)]
        return request_params

    def add_tool(
        self,
        tool: Union[Toolkit, Callable, Dict, Function],
        strict: bool = False,
        agent: Optional[Any] = None,
    ) -> None:
        """
        Adds tools to the model.

        Args:
            tool: The tool to add. Can be a Tool, Toolkit, Callable, dict, or Function.
            strict: If True, raise an error if the tool is not a Toolkit or Callable.
            agent: The agent to associate with the tool.
        """
        if self.function_declarations is None:
            self.function_declarations = []

        # If the tool is a Tool or Dict, log a warning.
        if isinstance(tool, Dict):
            logger.warning("Tool of type 'dict' is not yet supported by Gemini.")

        # If the tool is a Callable or Toolkit, add its functions to the Model
        elif callable(tool) or isinstance(tool, Toolkit) or isinstance(tool, Function):
            if self._functions is None:
                self._functions: Dict[str, Any] = {}

            if isinstance(tool, Toolkit):
                # For each function in the toolkit, process entrypoint and add to self.tools
                for name, func in tool.functions.items():
                    # If the function does not exist in self._functions, add to self.tools
                    if name not in self._functions:
                        func._agent = agent
                        func.process_entrypoint()
                        self._functions[name] = func
                        function_declaration = _build_function_declaration(func)
                        self.function_declarations.append(function_declaration)
                        logger.debug(f"Function {name} from {tool.name} added to model.")

            elif isinstance(tool, Function):
                if tool.name not in self._functions:
                    tool._agent = agent
                    tool.process_entrypoint()
                    self._functions[tool.name] = tool

                    function_declaration = _build_function_declaration(tool)
                    self.function_declarations.append(function_declaration)
                    logger.debug(f"Function {tool.name} added to model.")

            elif callable(tool):
                try:
                    function_name = tool.__name__
                    if function_name not in self._functions:
                        func = Function.from_callable(tool)
                        self._functions[func.name] = func
                        function_declaration = _build_function_declaration(func)
                        self.function_declarations.append(function_declaration)
                        logger.debug(f"Function '{func.name}' added to model.")
                except Exception as e:
                    logger.warning(f"Could not add function {tool}: {e}")

    def invoke(self, messages: List[Message]):
        """
        Invokes the model with a list of messages and returns the response.

        Args:
            messages (List[Message]): The list of messages to send to the model.

        Returns:
            GenerateContentResponse: The response from the model.
        """
        return self.get_client().generate_content(contents=_format_messages(messages))

    def invoke_stream(self, messages: List[Message]):
        """
        Invokes the model with a list of messages and returns the response as a stream.

        Args:
            messages (List[Message]): The list of messages to send to the model.

        Returns:
            Iterator[GenerateContentResponse]: The response from the model as a stream.
        """
        yield from self.get_client().generate_content(
            contents=_format_messages(messages),
            stream=True,
        )

    def update_usage_metrics(
        self,
        assistant_message: Message,
        usage: Optional[ResultGenerateContentResponse] = None,
        metrics: Metrics = Metrics(),
    ) -> None:
        """
        Update the usage metrics.

        Args:
            assistant_message (Message): The assistant message.
            usage (ResultGenerateContentResponse): The usage metrics.
            metrics (Metrics): The metrics to update.
        """
        if usage:
            metrics.input_tokens = usage.prompt_token_count or 0
            metrics.output_tokens = usage.candidates_token_count or 0
            metrics.total_tokens = usage.total_token_count or 0

        self._update_model_metrics(metrics_for_run=metrics)
        self._update_assistant_message_metrics(assistant_message=assistant_message, metrics_for_run=metrics)

    def create_assistant_message(self, response: GenerateContentResponse, metrics: Metrics) -> Message:
        """
        Create an assistant message from the response.

        Args:
            response (GenerateContentResponse): The model response.
            metrics (Metrics): The metrics to update.

        Returns:
            Message: The assistant message.
        """
        message_data = MessageData()

        message_data.response_block = response.candidates[0].content
        message_data.response_role = message_data.response_block.role
        message_data.response_parts = message_data.response_block.parts
        message_data.response_usage = response.usage_metadata

        if message_data.response_parts is not None:
            for part in message_data.response_parts:
                part_dict = type(part).to_dict(part)

                # Extract text if present
                if "text" in part_dict:
                    message_data.response_content = part_dict.get("text")

                # Parse function calls
                if "function_call" in part_dict:
                    message_data.response_tool_calls.append(
                        {
                            "type": "function",
                            "function": {
                                "name": part_dict.get("function_call").get("name"),
                                "arguments": json.dumps(part_dict.get("function_call").get("args")),
                            },
                        }
                    )

        # -*- Create assistant message
        assistant_message = Message(
            role=message_data.response_role or "model",
            content=message_data.response_content,
        )

        # -*- Update assistant message if tool calls are present
        if len(message_data.response_tool_calls) > 0:
            assistant_message.tool_calls = message_data.response_tool_calls

        # -*- Update usage metrics
        self.update_usage_metrics(assistant_message, message_data.response_usage, metrics)
        return assistant_message

    def format_function_call_results(
        self,
        function_call_results: List[Message],
        messages: List[Message],
    ):
        """
        Processes the results of function calls and appends them to messages.

        Args:
            function_call_results (List[Message]): The results from running function calls.
            messages (List[Message]): The list of conversation messages.
        """
        if function_call_results:
            combined_content: List = []
            combined_function_result: List = []

            for result in function_call_results:
                combined_content.append(result.content)
                combined_function_result.append((result.tool_name, result.content))

            messages.append(
                Message(role="tool", content=combined_content, combined_function_details=combined_function_result)
            )

    def handle_tool_calls(self, assistant_message: Message, messages: List[Message], model_response: ModelResponse):
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): A list of messages.
            model_response (ModelResponse): The model response.

        Returns:
            Optional[ModelResponse]: The updated model response.
        """
        if assistant_message.tool_calls:
            if model_response.tool_calls is None:
                model_response.tool_calls = []
            model_response.content = assistant_message.get_content_string() or ""
            function_calls_to_run = self._get_function_calls_to_run(
                assistant_message, messages, error_response_role="tool"
            )

            if self.show_tool_calls:
                if len(function_calls_to_run) == 1:
                    model_response.content += f"\n - Running: {function_calls_to_run[0].get_call_str()}\n\n"
                elif len(function_calls_to_run) > 1:
                    model_response.content += "\nRunning:"
                    for _f in function_calls_to_run:
                        model_response.content += f"\n - {_f.get_call_str()}"
                    model_response.content += "\n\n"

            function_call_results: List[Message] = []
            for function_call_response in self.run_function_calls(
                function_calls=function_calls_to_run,
                function_call_results=function_call_results,
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)

            self.format_function_call_results(function_call_results, messages)

            return model_response
        return None

    def response(self, messages: List[Message]) -> ModelResponse:
        """
        Send a generate cone content request to the model and return the response.

        Args:
            messages (List[Message]): The list of messages to send to the model.

        Returns:
            ModelResponse: The model response.
        """
        logger.debug("---------- Gemini Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        response: GenerateContentResponse = self.invoke(messages=messages)
        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = self.create_assistant_message(response=response, metrics=metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Update model response with assistant message content
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()

        # -*- Handle tool calls
        if self.handle_tool_calls(assistant_message, messages, model_response) is not None:
            response_after_tool_calls = self.response(messages=messages)
            if response_after_tool_calls.content is not None:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content

            return model_response

        logger.debug("---------- Gemini Response End ----------")
        return model_response

    def handle_stream_tool_calls(self, assistant_message: Message, messages: List[Message]):
        """
        Parse and run function calls and append the results to messages.

        Args:
            assistant_message (Message): The assistant message containing tool calls.
            messages (List[Message]): The list of conversation messages.

        Yields:
            Iterator[ModelResponse]: Yields model responses during function execution.
        """
        if assistant_message.tool_calls:
            function_calls_to_run = self._get_function_calls_to_run(
                assistant_message, messages, error_response_role="tool"
            )

            if self.show_tool_calls:
                if len(function_calls_to_run) == 1:
                    yield ModelResponse(content=f"\n - Running: {function_calls_to_run[0].get_call_str()}\n\n")
                elif len(function_calls_to_run) > 1:
                    yield ModelResponse(content="\nRunning:")
                    for _f in function_calls_to_run:
                        yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                    yield ModelResponse(content="\n\n")

            function_call_results: List[Message] = []
            for intermediate_model_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results
            ):
                yield intermediate_model_response

            self.format_function_call_results(function_call_results, messages)

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Send a generate content request to the model and return the response as a stream.

        Args:
            messages (List[Message]): The list of messages to send to the model.

        Yields:
            Iterator[ModelResponse]: The model responses
        """
        logger.debug("---------- Gemini Response Start ----------")
        self._log_messages(messages)
        message_data = MessageData()
        metrics = Metrics()

        metrics.start_response_timer()
        for response in self.invoke_stream(messages=messages):
            message_data.response_block = response.candidates[0].content
            message_data.response_role = message_data.response_block.role
            message_data.response_parts = message_data.response_block.parts

            if message_data.response_parts is not None:
                for part in message_data.response_parts:
                    part_dict = type(part).to_dict(part)

                    # -*- Yield text if present
                    if "text" in part_dict:
                        text = part_dict.get("text")
                        yield ModelResponse(content=text)
                        message_data.response_content += text
                        metrics.output_tokens += 1
                        if metrics.output_tokens == 1:
                            metrics.time_to_first_token = metrics.response_timer.elapsed
                    else:
                        message_data.valid_response_parts = message_data.response_parts

                    # -*- Skip function calls if there are no parts
                    if not message_data.response_block.parts and message_data.response_parts:
                        continue
                    # -*- Parse function calls
                    if "function_call" in part_dict:
                        message_data.response_tool_calls.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": part_dict.get("function_call").get("name"),
                                    "arguments": json.dumps(part_dict.get("function_call").get("args")),
                                },
                            }
                        )
            message_data.response_usage = response.usage_metadata
        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(
            role=message_data.response_role or "model",
            content=message_data.response_content,
        )

        # -*- Update assistant message if tool calls are present
        if len(message_data.response_tool_calls) > 0:
            assistant_message.tool_calls = message_data.response_tool_calls

        # -*- Update usage metrics
        self.update_usage_metrics(assistant_message, message_data.response_usage, metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield from self.handle_stream_tool_calls(assistant_message, messages)
            yield from self.response_stream(messages=messages)

        logger.debug("---------- Gemini Response End ----------")

    async def ainvoke(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def ainvoke_stream(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def aresponse_stream(self, messages: List[Message]) -> ModelResponse:
        raise NotImplementedError(f"Async not supported on {self.name}.")
