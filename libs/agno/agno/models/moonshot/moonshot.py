from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.media import File, Video
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_error, log_warning


def _media_cache_key(media: Union[File, Video]) -> Optional[str]:
    """Stable key identifying a media object, so it is uploaded at most once per instance."""
    import hashlib

    if media.content is not None:
        data = media.content if isinstance(media.content, bytes) else str(media.content).encode("utf-8")
        return "content:" + hashlib.sha256(data).hexdigest()
    if media.filepath is not None:
        return "path:" + str(media.filepath)
    if media.url is not None:
        return "url:" + str(media.url)
    return None


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

    Media is handled to match what Kimi accepts:
    - Images are sent inline as base64 in the message content (the inherited behaviour),
      so no upload is needed.
    - Files (PDF, docx, code, ...) cannot be attached inline; each is uploaded to the
      Files endpoint with ``purpose="file-extract"``, its text is extracted, and that
      text is injected into the message.
    - Videos are uploaded with ``purpose="video"`` and referenced with a Moonshot storage
      URL (``ms://<file-id>``).
    Uploaded media is cached per instance, so it is not re-uploaded when the same file or
    video reappears across turns (e.g. with ``add_history_to_context``). See:
    https://platform.kimi.ai/docs/guide/use-kimi-vision-model

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

    # Caches keyed by media identity, so a file/video that reappears across turns (e.g.
    # with add_history_to_context) is uploaded at most once. Excluded from equality and
    # repr; to_dict enumerates fields explicitly, so these are not serialized either.
    _extracted_file_cache: Dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    _uploaded_video_cache: Dict[str, str] = field(default_factory=dict, repr=False, compare=False)

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

    def _upload_media(self, media: Union[File, Video], purpose: str) -> Optional[str]:
        """Upload a file or video to Moonshot's Files endpoint and return its file id.

        Mirrors ``OpenAIResponses._upload_file`` (``files.create`` -> ``id``) but works for
        both files and videos and lets the caller pick the ``purpose`` Kimi expects
        (``"file-extract"`` for documents, ``"video"`` for video). Returns None if the
        media could not be read or the upload failed.
        """
        import mimetypes
        from pathlib import Path
        from urllib.parse import urlparse

        # Derive a filename for the upload tuple.
        filename = getattr(media, "filename", None)
        if not filename and media.filepath is not None:
            filename = Path(str(media.filepath)).name
        if not filename and media.url is not None:
            filename = Path(urlparse(media.url).path).name
        if not filename:
            filename = "file"

        try:
            data = media.get_content_bytes()
        except Exception as e:
            log_error(f"Failed to read media '{filename}' for upload: {e}")
            return None
        if data is None:
            log_error(f"No content to upload for media '{filename}'.")
            return None

        mime_type = media.mime_type or mimetypes.guess_type(filename)[0]
        file_tuple = (filename, data, mime_type) if mime_type else (filename, data)

        try:
            result = self.get_client().files.create(file=file_tuple, purpose=purpose)  # type: ignore
            return result.id
        except Exception as e:
            log_error(f"Failed to upload media '{filename}' to Moonshot: {e}")
            return None

    def _extract_file_content(self, file: File) -> Optional[str]:
        """Return a file's extracted text, uploading and extracting it once and caching it."""
        key = _media_cache_key(file)
        if key is not None and key in self._extracted_file_cache:
            return self._extracted_file_cache[key]

        file_id = self._upload_media(file, purpose="file-extract")
        if file_id is None:
            return None

        try:
            content = self.get_client().files.content(file_id=file_id).text
        except Exception as e:
            log_error(f"Failed to extract file content from Moonshot: {e}")
            return None

        if key is not None:
            self._extracted_file_cache[key] = content
        return content

    def _upload_video_reference(self, video: Video) -> Optional[str]:
        """Return a Moonshot storage reference (``ms://<id>``) for a video, uploaded once."""
        key = _media_cache_key(video)
        if key is not None and key in self._uploaded_video_cache:
            return self._uploaded_video_cache[key]

        file_id = self._upload_media(video, purpose="video")
        if file_id is None:
            return None

        reference = f"ms://{file_id}"
        if key is not None:
            self._uploaded_video_cache[key] = reference
        return reference

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        """Adapt an OpenAI-formatted message to what Moonshot accepts.

        - Round-trips ``reasoning_content`` so models that carry reasoning across turns
          receive prior assistant turns' reasoning unchanged.
        - Replaces the OpenAI ``file`` content parts (which Kimi rejects) with each file's
          extracted text, following Kimi's upload-and-extract flow.
        - Attaches videos (which the base class drops) as ``ms://`` storage references.

        Images are left untouched: the base class already inlines them as base64
        ``image_url`` parts, which is exactly what Kimi's vision models accept.
        """
        # The base class logs "Video input is currently unsupported" and otherwise ignores
        # videos. We support them (below), so hide them across the super() call to avoid
        # the misleading warning, then restore them.
        videos = message.videos
        if videos:
            message.videos = None
        try:
            message_dict = super()._format_message(message, compress_tool_results)
        finally:
            if videos:
                message.videos = videos

        if message.reasoning_content is not None:
            message_dict["reasoning_content"] = message.reasoning_content

        if not message.files and not message.videos:
            return message_dict

        # Normalize content to a list of parts so media parts can be attached.
        content = message_dict.get("content")
        if isinstance(content, str):
            parts: List[Any] = [{"type": "text", "text": content}] if content else []
        elif isinstance(content, list):
            parts = content
        else:
            parts = []

        # Files: drop the OpenAI file parts Kimi rejects and inject the extracted text.
        if message.files:
            parts = [part for part in parts if not (isinstance(part, dict) and part.get("type") == "file")]
            for file in message.files:
                text = self._extract_file_content(file)
                if text:
                    name = file.filename or (str(file.filepath) if file.filepath else None) or file.url or "file"
                    parts.insert(0, {"type": "text", "text": f"Contents of {name}:\n\n{text}"})
                else:
                    log_warning(
                        f"Could not attach file to Moonshot request: {file.filename or file.filepath or file.url}"
                    )

        # Videos: the base class drops these, so upload and reference them with ms:// URLs.
        if message.videos:
            for video in message.videos:
                reference = self._upload_video_reference(video)
                if reference:
                    parts.append({"type": "video_url", "video_url": {"url": reference}})
                else:
                    log_warning(f"Could not attach video to Moonshot request: {video.filepath or video.url}")

        message_dict["content"] = parts
        return message_dict
