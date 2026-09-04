"""Serialization of run outputs into MCP tool results.

The run tools on the AgentOS MCP server return results sized for the consuming
LLM: MCP tool results are injected directly into the frontend model's context
window, so the default ("trimmed") mode carries the answer and a minimal set of
identifiers rather than the full run transcript. Raw dataclass serialization is
never used -- it dumps internal message history (including the system prompt)
over the wire and raises on binary media.
"""

import json
from base64 import b64encode
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

from mcp.types import (
    AudioContent,
    BlobResourceContents,
    ContentBlock,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
)

from agno.media import Audio, File, Image, Video
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.utils import run_status_string, serialized_paused_requirements
from agno.run.workflow import WorkflowRunOutput
from agno.utils.media import resolve_image_mime_type
from agno.utils.serialize import json_serializer

AnyRunOutput = Union[RunOutput, TeamRunOutput, WorkflowRunOutput]

# Default media types when an artifact does not carry an explicit one.
_DEFAULT_AUDIO_MIME = "audio/mpeg"
_DEFAULT_VIDEO_MIME = "video/mp4"
_DEFAULT_FILE_MIME = "application/octet-stream"


def _content_text(run_output: AnyRunOutput) -> str:
    """The run's answer as plain text (JSON for structured/output_schema content)."""
    if run_output.content is None:
        return ""
    return run_output.get_content_as_string()


def _audio_mime(artifact: Audio) -> str:
    if artifact.mime_type:
        return artifact.mime_type
    if artifact.format:
        return f"audio/{artifact.format.lower()}"
    return _DEFAULT_AUDIO_MIME


def _image_block(image: Any) -> Optional[ImageContent]:
    """An MCP image block for an artifact holding raw bytes, else None."""
    if not isinstance(image, Image) or not isinstance(image.content, bytes):
        return None
    data = image.to_base64()
    if not data:
        return None
    return ImageContent(
        type="image",
        data=data,
        mimeType=resolve_image_mime_type(
            mime_type=image.mime_type, image_format=image.format, image_bytes=image.content
        ),
    )


def _audio_block(audio: Any) -> Optional[AudioContent]:
    """An MCP audio block for an artifact holding raw bytes, else None."""
    if not isinstance(audio, Audio) or not isinstance(audio.content, bytes):
        return None
    data = audio.to_base64()
    if not data:
        return None
    return AudioContent(type="audio", data=data, mimeType=_audio_mime(audio))


def _blob_block(artifact: Any, kind: str, default_mime: str) -> Optional[EmbeddedResource]:
    """An embedded MCP resource for bytes the protocol has no dedicated block for.

    MCP types text, images and audio directly; video and files travel as an embedded
    blob resource instead. The uri is a stable handle for the artifact, not a fetchable
    address -- the bytes are carried inline.
    """
    content = getattr(artifact, "content", None)
    if not isinstance(content, bytes):
        return None
    name = getattr(artifact, "filename", None) or str(getattr(artifact, "id", None) or kind)
    return EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(
            uri=f"agno://tool-result/{kind}/{quote(str(name), safe='')}",
            mimeType=getattr(artifact, "mime_type", None) or default_mime,
            blob=b64encode(content).decode("ascii"),
        ),
    )


def _link_block(artifact: Any, kind: str) -> Optional[ResourceLink]:
    """A link to media the tool produced somewhere else.

    Generation toolkits usually hand back a URL rather than bytes -- Giphy returns the
    gif's address, Replicate and Luma the rendered file's -- and that URL IS the result.
    Skipping it leaves the caller holding "generated successfully" and nothing to open.
    MCP types this exactly: a resource_link points at a resource without inlining it, so
    the bytes are still not fetched on the server's behalf. Reached only after the
    inlining path declined, so an artifact holding bytes never arrives here.
    """
    url = getattr(artifact, "url", None)
    if not url:
        return None
    try:
        return ResourceLink(
            type="resource_link",
            uri=url,
            name=str(getattr(artifact, "filename", None) or getattr(artifact, "id", None) or kind),
            mimeType=getattr(artifact, "mime_type", None),
        )
    except Exception:
        # A url the protocol will not accept as a uri is not worth failing the call over.
        return None


def _media_blocks(run_output: AnyRunOutput) -> List[ContentBlock]:
    """MCP content blocks for generated media that carries raw bytes.

    URL- or filepath-only artifacts are skipped: the bytes are not in hand, and
    fetching them on the server's behalf is not this layer's job. Their ids remain
    discoverable via ``result_mode="full"``.
    """
    blocks: List[ContentBlock] = []
    for image in getattr(run_output, "images", None) or []:
        block = _image_block(image)
        if block is not None:
            blocks.append(block)
    for audio in getattr(run_output, "audio", None) or []:
        audio_block = _audio_block(audio)
        if audio_block is not None:
            blocks.append(audio_block)
    return blocks


def build_custom_tool_result(result: Any) -> "Any":
    """Build the MCP ``ToolResult`` for a custom tool that returned an Agno ``ToolResult``.

    Without this the object reaches FastMCP's generic serializer, which JSON-dumps the
    whole model -- the caller reads ``{"content": "...", "metadata": null, "images":
    null, ...}`` instead of the answer -- and raises outright on raw media bytes, which
    are not valid UTF-8.

    Text becomes the first content block, images and audio become their MCP block types,
    and videos and files travel as embedded blob resources. An artifact that carries only
    a url becomes a resource_link: generation toolkits return the address rather than the
    bytes, and that address is the result. ``structuredContent`` mirrors the answer under
    ``content`` alongside the tool's own metadata, matching what the run tools publish.
    """
    from fastmcp.tools import ToolResult

    text = getattr(result, "content", None) or ""
    blocks: List[ContentBlock] = [TextContent(type="text", text=text)]
    for image in getattr(result, "images", None) or []:
        block = _image_block(image) or _link_block(image, "image")
        if block is not None:
            blocks.append(block)
    for audio in getattr(result, "audios", None) or []:
        audio_block = _audio_block(audio) or _link_block(audio, "audio")
        if audio_block is not None:
            blocks.append(audio_block)
    for video in getattr(result, "videos", None) or []:
        if isinstance(video, Video):
            video_block = _blob_block(video, "video", _DEFAULT_VIDEO_MIME) or _link_block(video, "video")
            if video_block is not None:
                blocks.append(video_block)
    for file in getattr(result, "files", None) or []:
        if isinstance(file, File):
            file_block = _blob_block(file, "file", _DEFAULT_FILE_MIME) or _link_block(file, "file")
            if file_block is not None:
                blocks.append(file_block)

    structured: Dict[str, Any] = {"content": text}
    metadata = getattr(result, "metadata", None)
    if metadata:
        structured["metadata"] = _json_safe(metadata)
    return ToolResult(content=blocks, structured_content=structured)


def _json_safe(data: Dict[str, Any]) -> Dict[str, Any]:
    """Force a dict through JSON so enum/datetime leftovers cannot break the transport."""
    return json.loads(json.dumps(data, default=json_serializer))


def trimmed_structured_content(run_output: AnyRunOutput, content_text: Optional[str] = None) -> Dict[str, Any]:
    structured: Dict[str, Any] = {
        "run_id": run_output.run_id,
        "session_id": run_output.session_id,
        "status": run_status_string(run_output),
        # The answer rides in BOTH result fields: clients that render
        # structuredContent when it is present (Claude Code among them) would
        # otherwise show metadata with no answer, and the official MCP servers keep
        # the two fields mirrored the same way. ``content_text`` lets the caller pass
        # the final text block (the paused/no-continue placeholder and REST-recovery
        # hint) so the two fields stay identical, not just for completed runs.
        "content": _content_text(run_output) if content_text is None else content_text,
    }
    # The component id is the handle for continue_run/get_sessions. The generic run
    # tools' callers already know it (they passed it), but an exposed tool's caller only
    # knows the tool name -- which may be an as_tool() override -- so the result must
    # carry the id or a paused run is unresumable.
    for key in ("agent_id", "team_id", "workflow_id"):
        value = getattr(run_output, key, None)
        if value:
            structured[key] = value
    requirements = serialized_paused_requirements(run_output)
    if requirements is not None:
        structured["requirements"] = requirements
    return _json_safe(structured)


def build_run_tool_result(
    run_output: AnyRunOutput, result_mode: str = "trimmed", continue_run_available: bool = True
) -> "Any":
    """Build the MCP ``ToolResult`` for a completed (or paused) run.

    ``trimmed`` (default): answer text + generated media as MCP content blocks,
    with ``structuredContent`` carrying run_id / session_id / status, the answer
    mirrored under ``content``, the owning component id (``agent_id``/``team_id``/
    ``workflow_id`` — the continue_run handle), and, when paused, the unresolved
    requirements a continue call must address.

    ``full``: text content with ``structuredContent`` set to the run's complete
    ``to_dict()`` (media base64-encoded there — no separate media blocks, so large
    payloads are not shipped twice).
    """
    from fastmcp.tools import ToolResult

    text = _content_text(run_output)
    if not text and getattr(run_output, "is_paused", False):
        requirements = serialized_paused_requirements(run_output) or []
        text = f"Run paused: {len(requirements)} requirement(s) awaiting resolution."
    if getattr(run_output, "is_paused", False) and not continue_run_available:
        # continue_run rides along with exposures by default, so this fires only when
        # the deployer opted out (lifecycle_tools=False / exclude_tags={"lifecycle"},
        # or tag scoping that drops both core and lifecycle). The paused run is then a
        # dead end over MCP -- say so at the moment it happens instead of letting the
        # client hunt for a tool that is not registered.
        text = (
            f"{text} The continue_run tool is not registered on this server; resume this run over "
            "the REST API, or re-enable the run-lifecycle tools (lifecycle_tools=True, and do not "
            'exclude the "lifecycle" tag).'
        ).strip()

    content: List[ContentBlock] = [TextContent(type="text", text=text)]

    if result_mode == "full":
        structured = _json_safe(run_output.to_dict())
    else:
        content.extend(_media_blocks(run_output))
        # Pass the final text so structuredContent["content"] carries the same message
        # the text block does -- including the paused / no-continue REST-recovery hint.
        structured = trimmed_structured_content(run_output, content_text=text)

    return ToolResult(content=content, structured_content=structured)


# Per-run fields kept when rendering conversation history. The full RunSchema carries the
# message transcript (system prompt included), events, and reasoning traces -- like the run
# tools, the history tool ships only what a frontend model needs, not the raw internals.
# Lives here so the two "what MCP clients see of a run" policies (fresh results above,
# history reads) stay in one file.
SESSION_RUN_HISTORY_FIELDS = (
    "run_id",
    "run_input",
    "content",
    "status",
    "created_at",
    "agent_id",
    "team_id",
    "workflow_id",
)


def trim_session_run(run: Any) -> Dict[str, Any]:
    """Compact view of one persisted run for conversation-history reads."""
    data = run.model_dump() if hasattr(run, "model_dump") else dict(run)
    return {key: data[key] for key in SESSION_RUN_HISTORY_FIELDS if data.get(key) is not None}
