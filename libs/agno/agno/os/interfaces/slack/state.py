from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Literal, Optional

from typing_extensions import TypedDict

if TYPE_CHECKING:
    from agno.media import Audio, File, Image, Video
    from agno.run.base import BaseRunOutputEvent

# Literal not Enum — values flow directly into Slack API dicts as plain strings.
# "pending" is semantically "queued / awaiting external input"; distinguishing it
# from "in_progress" ("actively working") matters for HITL pauses — Slack's AI
# Stream UI treats in_progress cards that outlive the stream idle window as
# errors, whereas pending cards represent legitimate waits.
TaskStatus = Literal["pending", "in_progress", "complete", "error"]


class TaskUpdateDict(TypedDict):
    type: str
    id: str
    title: str
    status: TaskStatus


@dataclass
class TaskCard:
    title: str
    status: TaskStatus = "in_progress"


@dataclass
class StreamState:
    # Slack thread title — set once on first content to avoid repeated API calls
    title_set: bool = False
    # Fallback ID generator — errors may lack tool_call_id so we synthesize one
    error_count: int = 0

    # Accumulates streamed text until flushed to Slack via stream.append()
    text_buffer: str = ""

    # Models can reason multiple times per run — each round needs a unique card ID
    reasoning_round: int = 0

    # Maps card_id → TaskCard; tracks all emitted task cards for status updates
    task_cards: Dict[str, TaskCard] = field(default_factory=dict)

    # Media collected during streaming — Slack requires separate upload after stream ends
    images: List["Image"] = field(default_factory=list)
    videos: List["Video"] = field(default_factory=list)
    audio: List["Audio"] = field(default_factory=list)
    files: List["File"] = field(default_factory=list)

    # Determines event suppression rules — workflows hide inner agent noise
    entity_type: Literal["agent", "team", "workflow"] = "agent"
    # Compared against chunk.agent_name to detect team member vs leader content
    entity_name: str = ""

    # Captured from StepOutput — WorkflowCompleted may have None content
    workflow_final_content: str = ""

    # Terminal status for final flush — "error" triggers error styling in Slack
    terminal_status: Optional[TaskStatus] = None

    # Tracks content sent for stream rotation decisions in long-running runs
    stream_chars_sent: int = 0

    # HITL: stashed by _on_run_paused so router can post Block Kit approval card
    # after stream.stop() — AsyncChatStream can't emit Block Kit, only markdown
    paused_event: Optional["BaseRunOutputEvent"] = None

    def track_task(self, key: str, title: str, status: TaskStatus = "in_progress") -> None:
        self.task_cards[key] = TaskCard(title=title, status=status)

    def complete_task(self, key: str) -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "complete"

    def error_task(self, key: str) -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "error"

    def resolve_all_pending(self, status: TaskStatus = "complete") -> List[TaskUpdateDict]:
        # Close orphaned in_progress cards — model may skip ToolCallCompleted if
        # it errors mid-call or the run terminates unexpectedly
        chunks: List[TaskUpdateDict] = []
        for key, card in self.task_cards.items():
            if card.status == "in_progress":
                card.status = status  # type: ignore[assignment]
                chunks.append(TaskUpdateDict(type="task_update", id=key, title=card.title, status=status))
        return chunks

    def append_content(self, text: str) -> None:
        self.text_buffer += str(text)

    def append_error(self, error_msg: str) -> None:
        self.text_buffer += f"\n_Error: {error_msg}_"

    def has_content(self) -> bool:
        return bool(self.text_buffer)

    def flush(self) -> str:
        result = self.text_buffer
        self.text_buffer = ""
        return result

    def collect_media(self, chunk: BaseRunOutputEvent) -> None:
        # Slack AI-Stream protocol can't embed media — files must be uploaded
        # separately after stream.stop() via files_upload_v2 API
        for img in getattr(chunk, "images", None) or []:
            if img not in self.images:
                self.images.append(img)
        for vid in getattr(chunk, "videos", None) or []:
            if vid not in self.videos:
                self.videos.append(vid)
        for aud in getattr(chunk, "audio", None) or []:
            if aud not in self.audio:
                self.audio.append(aud)
        for f in getattr(chunk, "files", None) or []:
            if f not in self.files:
                self.files.append(f)
