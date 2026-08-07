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
    After an upload the Moonshot file id is stored on the media object's ``id`` field, so
    a file or video that reappears across turns (e.g. with ``add_history_to_context``) is
    not uploaded again. See:
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
        except Exception as e:
            log_error(f"Failed to upload media '{filename}' to Moonshot: {e}")
            return None

        # The upload response carries a status; surface a failed parse instead of letting
        # the follow-up content fetch fail with an opaque 404.
        status = getattr(result, "status", None)
        if status in ("error", "failed"):
            log_error(
                f"Moonshot could not process media '{filename}': {getattr(result, 'status_details', None) or status}"
            )
            return None
        return result.id

    def _extract_file_content(self, file: File) -> Optional[str]:
        """Return a file's extracted text, uploading it at most once.

        The Moonshot file id is written back to ``file.id`` after the upload, so when the
        same File reappears on a later turn (e.g. with ``add_history_to_context``) only
        the extracted text is fetched — the file is not uploaded again. No state is kept
        on the model instance; the id travels with the media object.
        """
        import time

        # A previously stored id is a hint, not a guarantee: it may be stale, deleted
        # server-side, or a foreign id set by the caller. Try it, but fall back to a
        # fresh upload instead of failing the file outright.
        if file.id:
            try:
                return self.get_client().files.content(file_id=file.id).text
            except Exception:
                log_warning(f"Stored Moonshot file id '{file.id}' is not retrievable, re-uploading.")

        file_id = self._upload_media(file, purpose="file-extract")
        if file_id is None:
            return None
        file.id = file_id

        # Uploads are parsed asynchronously ("created" -> "ok"), and fetching the content
        # of an unparsed file 404s. Mirror OpenAIResponses._create_vector_store: poll the
        # file status until parsing completes before fetching the extracted text.
        name = file.filename or file_id
        status: Optional[str] = None
        for attempt in range(5):
            if attempt:
                time.sleep(1.0)
            try:
                status = getattr(self.get_client().files.retrieve(file_id=file_id), "status", None)
            except Exception:
                continue
            if status in ("error", "failed"):
                log_error(f"Moonshot could not parse file '{name}': {status}")
                return None
            if status == "ok":
                break

        try:
            return self.get_client().files.content(file_id=file_id).text
        except Exception as e:
            log_error(f"Failed to extract file content from Moonshot (file status: {status}): {e}")
            return None

    def _video_reference(self, video: Video) -> Optional[str]:
        """Return a Moonshot storage reference (``ms://<id>``) for a video.

        The full reference is written back to ``video.id`` after the upload (Video ids
        are auto-generated UUIDs, so the ``ms://`` prefix is what marks a video as
        already uploaded). The video is uploaded at most once even when it reappears
        across turns; no state is kept on the model instance.
        """
        if video.id and video.id.startswith("ms://"):
            return video.id

        file_id = self._upload_media(video, purpose="video")
        if file_id is None:
            return None

        video.id = f"ms://{file_id}"
        return video.id

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        """Adapt an OpenAI-formatted message to what Moonshot accepts.

        - Round-trips ``reasoning_content`` so models that carry reasoning across turns
          receive prior assistant turns' reasoning unchanged.
        - Handles files itself (the base class would build an OpenAI ``file`` part that
          Kimi rejects): each file is uploaded and its extracted text injected, following
          Kimi's upload-and-extract flow.
        - Attaches videos (which the base class drops) as ``ms://`` storage references.

        Images are left untouched: the base class already inlines them as base64
        ``image_url`` parts, which is exactly what Kimi's vision models accept.
        """
        # Hide files and videos across the super() call: for files the base class would
        # download and base64-encode them into an OpenAI `file` part that Kimi rejects
        # (a wasted fetch for URL files); for videos it would just log "Video input is
        # currently unsupported". Both are handled below instead.
        files, videos = message.files, message.videos
        if files:
            message.files = None
        if videos:
            message.videos = None
        try:
            message_dict = super()._format_message(message, compress_tool_results)
        finally:
            if files:
                message.files = files
            if videos:
                message.videos = videos

        if message.reasoning_content is not None:
            message_dict["reasoning_content"] = message.reasoning_content

        if not files and not videos:
            return message_dict

        # Normalize content to a new list of parts. The base class may return the stored
        # message's own content list, so never mutate it in place — with history enabled
        # the same Message is re-formatted every turn and appended parts would accumulate.
        content = message_dict.get("content")
        if isinstance(content, str):
            parts: List[Any] = [{"type": "text", "text": content}] if content else []
        elif isinstance(content, list):
            parts = list(content)
        else:
            parts = []

        # Files: upload with purpose="file-extract" and inject the extracted text.
        if files:
            for file in files:
                text = self._extract_file_content(file)
                if text:
                    name = file.filename or (str(file.filepath) if file.filepath else None) or file.url or "file"
                    parts.insert(0, {"type": "text", "text": f"Contents of {name}:\n\n{text}"})
                else:
                    log_warning(
                        f"Could not attach file to Moonshot request: {file.filename or file.filepath or file.url}"
                    )

        # Videos: upload with purpose="video" and reference them with ms:// URLs.
        if videos:
            for video in videos:
                reference = self._video_reference(video)
                if reference:
                    parts.append({"type": "video_url", "video_url": {"url": reference}})
                else:
                    log_warning(f"Could not attach video to Moonshot request: {video.filepath or video.url}")

        message_dict["content"] = parts
        return message_dict
