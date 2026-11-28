import mimetypes
from dataclasses import dataclass, field
from os import getenv
from pathlib import Path
from typing import Any, AsyncIterator, ClassVar, Dict, List, Optional, Set, Tuple, Type, Union
from urllib.parse import urlparse

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError, ModelProviderError
from agno.media import File
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_warning
from agno.utils.openai import audio_to_message, images_to_message


@dataclass
class DeepSeek(OpenAILike):
    """
    A class for interacting with DeepSeek models.

    DeepSeek V4 models (deepseek-v4-flash, deepseek-v4-pro) run with thinking mode
    enabled by default. While thinking mode is active, the following parameters are
    accepted but have no effect (they are silently ignored by the API):
    - temperature
    - top_p
    - presence_penalty
    - frequency_penalty

    Thinking mode is controlled with the ``use_thinking`` flag:
    - ``use_thinking=None`` (default): thinking is on for thinking-capable models and
      off for the legacy non-thinking ids (deepseek-chat).
    - ``use_thinking=True``: force thinking on.
    - ``use_thinking=False``: turn thinking off (faster, cheaper responses).

    For agent scenarios, DeepSeek recommends ``reasoning_effort="max"``. It is left
    unset (None) by default so the API uses its own default ("high"); set it
    explicitly to opt in. Valid values are "high" and "max".

    For more information, see: https://api-docs.deepseek.com/guides/thinking_mode

    Attributes:
        id (str): The model id. Defaults to "deepseek-v4-flash".
        name (str): The model name. Defaults to "DeepSeek".
        provider (str): The provider name. Defaults to "DeepSeek".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.deepseek.com".
        use_thinking (Optional[bool]): Toggle thinking mode. None uses the model default.
        file_parsing_purpose (str): Files API purpose used when uploading documents (PDF, Word,
            PowerPoint). "text_recognition" (default) parses text only;
            "rich_layout_recognition" also gives the model the figures in the document.

    File inputs are uploaded through the DeepSeek Files API at most once: the DeepSeek file id is
    written back to ``File.id`` (as ``deepseek://<file-id>``), so it is stored with the session and
    the file is not uploaded (and billed) again when it reappears in the history, even after a
    restart. A file that cannot be read or uploaded raises ``ModelProviderError`` instead of being
    silently dropped from the request.
    """

    id: str = "deepseek-v4-flash"
    name: str = "DeepSeek"
    provider: str = "DeepSeek"

    api_key: Optional[str] = field(default_factory=lambda: getenv("DEEPSEEK_API_KEY"))
    base_url: str = "https://api.deepseek.com"

    # Toggle thinking mode. None = use the model default (on for thinking-capable models,
    # off for the legacy non-thinking ids). True = force on, False = force off.
    use_thinking: Optional[bool] = None

    # Files API purpose for documents that need parsing (PDF, DOC/DOCX, PPT/PPTX).
    # "text_recognition" or "rich_layout_recognition".
    file_parsing_purpose: str = "text_recognition"

    # DeepSeek supports JSON mode (response_format={"type": "json_object"}) but not
    # native/json_schema structured outputs, so output_schema needs use_json_mode=True.
    supports_native_structured_outputs: bool = False

    # Model ids that should NOT have thinking enabled by default. The legacy ids still
    # work and route server-side: deepseek-chat -> non-thinking mode of deepseek-v4-flash,
    # deepseek-reasoner -> thinking mode of deepseek-v4-flash. Only deepseek-chat needs to
    # opt out of thinking here (deepseek-reasoner is already a thinking model).
    _non_thinking_model_ids: ClassVar[Set[str]] = {
        "deepseek-chat",
    }

    def _thinking_enabled(self) -> bool:
        """Resolve whether thinking mode should be on for this request.

        An explicit ``use_thinking`` flag always wins; otherwise thinking-capable models
        default to on and the legacy non-thinking ids default to off.
        """
        if self.use_thinking is not None:
            return self.use_thinking
        return self.id not in self._non_thinking_model_ids

    def get_request_params(
        self,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
    ) -> Dict[str, Any]:
        request_params = super().get_request_params(
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )

        if self._thinking_enabled():
            # Merge with any user-supplied extra_body and never overwrite an explicit
            # thinking setting (so a raw extra_body override still takes precedence).
            extra_body = request_params.get("extra_body") or {}
            extra_body.setdefault("thinking", {"type": "enabled"})
            request_params["extra_body"] = extra_body
        else:
            # No thinking: reasoning_effort has no effect, so strip it. Only send an
            # explicit disabled flag when the user turned a thinking-capable model off;
            # the legacy non-thinking ids are already non-thinking server-side.
            request_params.pop("reasoning_effort", None)
            if self.use_thinking is False:
                extra_body = request_params.get("extra_body") or {}
                extra_body.setdefault("thinking", {"type": "disabled"})
                request_params["extra_body"] = extra_body

        return request_params

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("DEEPSEEK_API_KEY")
            if not self.api_key:
                # Raise error immediately if key is missing
                raise ModelAuthenticationError(
                    message="DEEPSEEK_API_KEY not set. Please set the DEEPSEEK_API_KEY environment variable.",
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

    # Mime types that DeepSeek's Files API accepts under purpose="user_data" (text, sheets, ebooks).
    # Everything else (PDF, Word, PowerPoint, images) is a "document" and needs a parsing purpose.
    _USER_DATA_MIME_PREFIXES: ClassVar[Tuple[str, ...]] = ("text/",)
    _USER_DATA_MIME_TYPES: ClassVar[Set[str]] = {
        "application/json",
        "application/x-javascript",
        "application/x-python",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/epub+zip",
        "application/x-mobipocket-ebook",
    }

    # Prefix that marks a File.id as an uploaded DeepSeek file id (File.id defaults to a UUID).
    _FILE_ID_PREFIX: ClassVar[str] = "deepseek://"

    def _upload_purpose_for(self, mime_type: Optional[str]) -> str:
        if mime_type and (
            mime_type.startswith(self._USER_DATA_MIME_PREFIXES) or mime_type in self._USER_DATA_MIME_TYPES
        ):
            return "user_data"
        return self.file_parsing_purpose

    def _stored_file_id(self, file: File) -> Optional[str]:
        """Return the DeepSeek file id this File already refers to, if any.

        A string in ``file.external`` is an already uploaded DeepSeek ``file_id``; a ``file.id``
        with the ``deepseek://`` prefix was written back by a previous upload.
        """
        if isinstance(file.external, str) and file.external:
            return file.external
        if file.id and file.id.startswith(self._FILE_ID_PREFIX):
            return file.id[len(self._FILE_ID_PREFIX) :]
        return None

    @staticmethod
    def _upload_filename(file: File) -> str:
        if file.filename:
            return file.filename
        if file.media_reference is not None and file.media_reference.filename:
            return file.media_reference.filename
        if file.filepath is not None:
            return Path(str(file.filepath)).name
        if file.url is not None:
            return Path(urlparse(file.url).path).name or "file"
        return "file"

    def _file_error(self, action: str, file: File, error: Optional[Exception] = None) -> ModelProviderError:
        status_code = getattr(error, "status_code", None)
        return ModelProviderError(
            message=f"Failed to {action} file '{self._upload_filename(file)}' for DeepSeek: {error or 'no content'}",
            status_code=status_code if isinstance(status_code, int) else 400,
            model_name=self.name,
            model_id=self.id,
        )

    def _upload_request(self, file: File, data: Optional[bytes]) -> Tuple[Tuple[str, bytes], str]:
        """Build the (file tuple, purpose) for an upload, raising if there is nothing to send."""
        if not data:
            raise self._file_error("read", file)
        filename = self._upload_filename(file)
        mime_type = file.mime_type or mimetypes.guess_type(filename)[0]
        return (filename, data), self._upload_purpose_for(mime_type)

    def _upload_file(self, file: File) -> str:
        """Upload a File through the Files API, record the id on ``file.id`` and return it."""
        try:
            data = file.get_content_bytes()
        except Exception as e:
            raise self._file_error("read", file, e) from e
        file_tuple, purpose = self._upload_request(file, data)
        try:
            uploaded = self.get_client().files.create(file=file_tuple, purpose=purpose)  # type: ignore[arg-type]
        except Exception as e:
            raise self._file_error("upload", file, e) from e
        file.id = f"{self._FILE_ID_PREFIX}{uploaded.id}"
        return uploaded.id

    async def _aupload_file(self, file: File) -> str:
        """Async variant of ``_upload_file``, so ``arun`` does not block the event loop."""
        try:
            data = await file.aget_content_bytes()
        except Exception as e:
            raise self._file_error("read", file, e) from e
        file_tuple, purpose = self._upload_request(file, data)
        try:
            uploaded = await self.get_async_client().files.create(file=file_tuple, purpose=purpose)  # type: ignore[arg-type]
        except Exception as e:
            raise self._file_error("upload", file, e) from e
        file.id = f"{self._FILE_ID_PREFIX}{uploaded.id}"
        return uploaded.id

    async def _aupload_pending_files(self, messages: List[Message]) -> None:
        """Upload every not-yet-uploaded File with the async client before the messages are formatted."""
        for message in messages:
            for file in message.files or []:
                if self._stored_file_id(file) is None:
                    await self._aupload_file(file)

    def _format_file_part(self, file: File) -> Dict[str, Any]:
        """Format a File as a DeepSeek chat-completions file part.

        DeepSeek's file part is flat (``{"type": "file", "file_id": ...}``), not the nested OpenAI
        shape, and documents can only be referenced by ``file_id``. Files are therefore uploaded
        through the Files API first, once (see ``_stored_file_id``).

        Raises:
            ModelProviderError: If the file cannot be read or the upload fails.
        """
        file_id = self._stored_file_id(file) or self._upload_file(file)
        return {"type": "file", "file_id": file_id}

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
        await self._aupload_pending_files(messages)
        return await super().ainvoke(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        )

    async def ainvoke_stream(  # type: ignore[override]
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        await self._aupload_pending_files(messages)
        async for response in super().ainvoke_stream(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        ):
            yield response

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.
            compress_tool_results: Whether to compress tool results.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        tool_result = message.get_content(use_compressed_content=compress_tool_results)

        message_dict: Dict[str, Any] = {
            "role": self.role_map[message.role] if self.role_map else self.default_role_map[message.role],
            "content": tool_result,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
            "reasoning_content": message.reasoning_content,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        # Ignore non-string message content
        # because we assume that the images/audio are already added to the message
        if (message.images is not None and len(message.images) > 0) or (
            message.audio is not None and len(message.audio) > 0
        ):
            # Ignore non-string message content
            # because we assume that the images/audio are already added to the message
            if isinstance(message.content, str):
                message_dict["content"] = [{"type": "text", "text": message.content}]
                if message.images is not None:
                    message_dict["content"].extend(images_to_message(images=message.images))

                if message.audio is not None:
                    message_dict["content"].extend(audio_to_message(audio=message.audio))

        if message.audio_output is not None:
            message_dict["content"] = ""
            message_dict["audio"] = {"id": message.audio_output.id}

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported.")

        if message.files is not None:
            # Ensure content is a list of parts
            content = message_dict.get("content")
            if isinstance(content, str):  # wrap existing text
                text = content
                message_dict["content"] = [{"type": "text", "text": text}]
            elif content is None:
                message_dict["content"] = []
            # Insert each file part before text parts
            for file in message.files:
                message_dict["content"].insert(0, self._format_file_part(file))

        # Manually add the content field even if it is None, without dropping the file parts
        if message.content is None and not isinstance(message_dict.get("content"), list):
            message_dict["content"] = ""
        return message_dict
