from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class DashScope(OpenAILike):
    """
    A class for interacting with Qwen models via DashScope API.

    Attributes:
        id (str): The model id. Defaults to "qwen-plus".
        name (str): The model name. Defaults to "Qwen".
        provider (str): The provider name. Defaults to "Qwen".
        api_key (Optional[str]): The DashScope API key.
        base_url (str): The base URL. Defaults to "https://dashscope-intl.aliyuncs.com/compatible-mode/v1".
        enable_thinking (bool): Enable thinking process (DashScope native parameter). Defaults to False.
        include_thoughts (Optional[bool]): Include thinking process in response (alternative parameter). Defaults to None.
    """

    id: str = "qwen-plus"
    name: str = "Qwen"
    provider: str = "Dashscope"

    api_key: Optional[str] = getenv("DASHSCOPE_API_KEY") or getenv("QWEN_API_KEY")
    base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    # Thinking parameters
    enable_thinking: bool = False
    include_thoughts: Optional[bool] = None
    thinking_budget: Optional[int] = None

    # DashScope supports structured outputs
    supports_native_structured_outputs: bool = True
    supports_json_schema_outputs: bool = True

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("DASHSCOPE_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="DASHSCOPE_API_KEY not set. Please set the DASHSCOPE_API_KEY environment variable.",
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

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        params = super().get_request_params(response_format=response_format, tools=tools, tool_choice=tool_choice)

        if self.include_thoughts is not None:
            self.enable_thinking = self.include_thoughts

        if self.enable_thinking is not None:
            params["extra_body"] = {
                "enable_thinking": self.enable_thinking,
            }

            if self.thinking_budget is not None:
                params["extra_body"]["thinking_budget"] = self.thinking_budget

        return params


    def _format_message(self, message: Message) -> Dict[str, Any]:
        formatted_message = super()._format_message(message)
        if isinstance(formatted_message['content'], list):
            for item in formatted_message['content']:
                if item.get('type') == 'input_audio':
                    # data:;base64,
                    audio_data = item.get('input_audio').get('data')
                    if audio_data and not audio_data.startswith("data:;base64,"):
                        item['input_audio']['data'] = f"data:;base64,{audio_data}"
        if message.videos is not None and len(message.videos) > 0:
            if isinstance(formatted_message["content"], str):
                formatted_message["content"] = [{"type": "text", "text": message.content}]
                formatted_message["content"].extend(self.video_to_message(video=message.videos))

        return formatted_message


    def video_to_message(self, video: Sequence[Video]) -> List[Dict[str, Any]]:
        """
        Add video to a message for the model. By default, we use the OpenAI video format but other Models
        can override this method to use a different video format.

        Args:
            video: Pre-formatted video data like {
                        "content": encoded_string,
                        "format": "mp4"
                    }

        Returns:
            Message content with video added in the format expected by the model
        """
        from urllib.parse import urlparse

        video_messages = []
        for video_snippet in video:
            encoded_string: Optional[str] = None
            video_format: Optional[str] = video_snippet.format

            # The video is raw data
            if video_snippet.content:
                encoded_string = base64.b64encode(video_snippet.content).decode("utf-8")
                if not video_format:
                    video_format = "mp4"  # Default format if not provided

            # The video is a URL
            elif video_snippet.url:
                video_bytes = video_snippet.get_content_bytes()
                if video_bytes is not None:
                    encoded_string = base64.b64encode(video_bytes).decode("utf-8")
                    if not video_format:
                        # Try to guess format from URL extension
                        try:
                            # Parse the URL first to isolate the path
                            parsed_url = urlparse(video_snippet.url)
                            # Get suffix from the path component only
                            video_format = Path(parsed_url.path).suffix.lstrip(".")
                            if not video_format:  # Handle cases like URLs ending in /
                                log_warning(
                                    f"Could not determine video format from URL path: {parsed_url.path}. Defaulting."
                                )
                                video_format = "mp4"
                        except Exception as e:
                            log_warning(
                                f"Could not determine video format from URL: {video_snippet.url}. Error: {e}. Defaulting."
                            )
                            video_format = "mp4"  # Default if guessing fails

            # The video is a file path
            elif video_snippet.filepath:
                path = Path(video_snippet.filepath)
                if path.exists() and path.is_file():
                    try:
                        with open(path, "rb") as video_file:
                            encoded_string = base64.b64encode(video_file.read()).decode("utf-8")
                        if not video_format:
                            video_format = path.suffix.lstrip(".")
                    except Exception as e:
                        log_error(f"Failed to read video file {path}: {e}")
                        continue  # Skip this video snippet if file reading fails
                else:
                    log_error(f"Video file not found or is not a file: {path}")
                    continue  # Skip if file doesn't exist

            # Append the message if we successfully processed the video
            if encoded_string and video_format: 
                video_messages.append(
                    {
                        "type": "video_url",
                        "video_url": {
                            "url": f"data:;base64,{encoded_string}",
                        },
                    },
                )
            else:
                log_error(f"Could not process video snippet: {video_snippet}")

        return video_messages

