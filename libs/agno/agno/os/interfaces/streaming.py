from __future__ import annotations

from typing import Any, List, Optional

from agno.agent import RunEvent


def normalize_event(event: str) -> str:
    # Strip "Team" prefix so agent and team events use the same handler dispatch
    return event.removeprefix("Team")


# Workflows orchestrate multiple agents via steps/loops/conditions. Without
# suppression, each inner agent's tool calls and reasoning events would flood
# the stream with low-level noise. We only show step-level progress.
# Values are NORMALIZED (no "Team" prefix) so one set covers agent + team events.
SUPPRESSED_IN_WORKFLOW: frozenset[str] = frozenset(
    {
        RunEvent.reasoning_started.value,
        RunEvent.reasoning_completed.value,
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
        RunEvent.tool_call_error.value,
        RunEvent.memory_update_started.value,
        RunEvent.memory_update_completed.value,
        RunEvent.run_content.value,
        RunEvent.run_intermediate_content.value,
        RunEvent.run_completed.value,
        RunEvent.run_error.value,
        RunEvent.run_cancelled.value,
    }
)


_AGENT_NAME_KEY_LIMIT = 20  # Keep task card keys short; no platform constraint, just readability


def member_name(chunk: Any, entity_name: str) -> Optional[str]:
    # Returns None when chunk belongs to the team leader (name matches entity_name)
    # or when chunk has no agent_name attribute
    name = getattr(chunk, "agent_name", None)
    if name and isinstance(name, str) and name != entity_name:
        return name
    return None


def task_id(agent_name: Optional[str], base_id: str) -> str:
    # Prefix card IDs per agent so concurrent tool calls from different
    # team members don't collide in the stream
    if agent_name:
        safe = agent_name.lower().replace(" ", "_")[:_AGENT_NAME_KEY_LIMIT]
        return f"{safe}_{base_id}"
    return base_id


def collect_media_from_chunk(state: Any, chunk: Any) -> None:
    # Dedup-accumulate images/videos/audio/files from streaming events.
    # State must expose images, videos, audio, files list attributes.
    for img in getattr(chunk, "images", None) or []:
        if img not in state.images:
            state.images.append(img)
    for vid in getattr(chunk, "videos", None) or []:
        if vid not in state.videos:
            state.videos.append(vid)
    for aud in getattr(chunk, "audio", None) or []:
        if aud not in state.audio:
            state.audio.append(aud)
    for f in getattr(chunk, "files", None) or []:
        if f not in state.files:
            state.files.append(f)


def chunk_text(text: str, max_len: int) -> List[str]:
    # Split on natural boundaries: paragraph > line > word > hard cut.
    # Used to fit long agent output into platform message size limits.
    if len(text) <= max_len:
        return [text]

    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        cut = remaining.rfind("\n\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, max_len)
        if cut <= 0:
            cut = max_len

        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    return chunks
