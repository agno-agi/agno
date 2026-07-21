"""Serialization of run outputs into MCP tool results.

The run tools on the AgentOS MCP server return results sized for the consuming
LLM: MCP tool results are injected directly into the frontend model's context
window, so the default ("trimmed") mode carries the answer and a minimal set of
identifiers rather than the full run transcript. Raw dataclass serialization is
never used -- it dumps internal message history (including the system prompt)
over the wire and raises on binary media.
"""

import json
from typing import Any, Dict, List, Optional, Union

from mcp.types import AudioContent, ContentBlock, ImageContent, TextContent

from agno.media import Audio, Image
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.utils.media import resolve_image_mime_type
from agno.utils.serialize import json_serializer

AnyRunOutput = Union[RunOutput, TeamRunOutput, WorkflowRunOutput]

# Default media type when an audio artifact does not carry an explicit mime type.
_DEFAULT_AUDIO_MIME = "audio/mpeg"


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


def _media_blocks(run_output: AnyRunOutput) -> List[ContentBlock]:
    """MCP content blocks for generated media that carries raw bytes.

    URL- or filepath-only artifacts are skipped: the bytes are not in hand, and
    fetching them on the server's behalf is not this layer's job. Their ids remain
    discoverable via ``result_mode="full"``.
    """
    blocks: List[ContentBlock] = []
    for image in getattr(run_output, "images", None) or []:
        if isinstance(image, Image) and isinstance(image.content, bytes):
            data = image.to_base64()
            if data:
                blocks.append(
                    ImageContent(
                        type="image",
                        data=data,
                        mimeType=resolve_image_mime_type(
                            mime_type=image.mime_type, image_format=image.format, image_bytes=image.content
                        ),
                    )
                )
    for audio in getattr(run_output, "audio", None) or []:
        if isinstance(audio, Audio) and isinstance(audio.content, bytes):
            data = audio.to_base64()
            if data:
                blocks.append(AudioContent(type="audio", data=data, mimeType=_audio_mime(audio)))
    return blocks


def _run_status(run_output: AnyRunOutput) -> str:
    status = getattr(run_output, "status", None)
    value = getattr(status, "value", status)
    return str(value) if value is not None else "COMPLETED"


def _paused_requirements(run_output: AnyRunOutput) -> Optional[List[Dict[str, Any]]]:
    """Serialized unresolved requirements when the run is paused, else None."""
    if not getattr(run_output, "is_paused", False):
        return None
    # Agents/teams expose active_requirements; workflows expose active_step_requirements.
    requirements = (
        getattr(run_output, "active_requirements", None) or getattr(run_output, "active_step_requirements", None) or []
    )
    serialized: List[Dict[str, Any]] = []
    for requirement in requirements:
        if hasattr(requirement, "to_dict"):
            serialized.append(requirement.to_dict())
        elif isinstance(requirement, dict):
            serialized.append(requirement)
    return serialized or None


def _json_safe(data: Dict[str, Any]) -> Dict[str, Any]:
    """Force a dict through JSON so enum/datetime leftovers cannot break the transport."""
    return json.loads(json.dumps(data, default=json_serializer))


def trimmed_structured_content(run_output: AnyRunOutput) -> Dict[str, Any]:
    structured: Dict[str, Any] = {
        "run_id": run_output.run_id,
        "session_id": run_output.session_id,
        "status": _run_status(run_output),
    }
    requirements = _paused_requirements(run_output)
    if requirements is not None:
        structured["requirements"] = requirements
    return _json_safe(structured)


def build_run_tool_result(run_output: AnyRunOutput, result_mode: str = "trimmed") -> "Any":
    """Build the MCP ``ToolResult`` for a completed (or paused) run.

    ``trimmed`` (default): answer text + generated media as MCP content blocks,
    with ``structuredContent`` limited to run_id / session_id / status and, when
    paused, the unresolved requirements a continue call must address.

    ``full``: text content with ``structuredContent`` set to the run's complete
    ``to_dict()`` (media base64-encoded there — no separate media blocks, so large
    payloads are not shipped twice).
    """
    from fastmcp.tools import ToolResult

    text = _content_text(run_output)
    if not text and getattr(run_output, "is_paused", False):
        requirements = _paused_requirements(run_output) or []
        text = f"Run paused: {len(requirements)} requirement(s) awaiting resolution."

    content: List[ContentBlock] = [TextContent(type="text", text=text)]

    if result_mode == "full":
        structured = _json_safe(run_output.to_dict())
    else:
        content.extend(_media_blocks(run_output))
        structured = trimmed_structured_content(run_output)

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
