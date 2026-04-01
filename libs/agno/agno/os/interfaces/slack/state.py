from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Literal, Optional

from typing_extensions import TypedDict

if TYPE_CHECKING:
    from agno.media import Audio, File, Image, Video
    from agno.run.base import BaseRunOutputEvent

# Literal not Enum — values flow directly into Slack API dicts as plain strings
TaskStatus = Literal["in_progress", "complete", "error"]


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
    # Incremented per error; used to generate unique fallback task card IDs
    error_count: int = 0

    text_buffer: str = ""

    # Counter for unique reasoning task card keys (reasoning_0, reasoning_1, ...)
    reasoning_round: int = 0

    task_cards: Dict[str, TaskCard] = field(default_factory=dict)

    images: List["Image"] = field(default_factory=list)
    videos: List["Video"] = field(default_factory=list)
    audio: List["Audio"] = field(default_factory=list)
    files: List["File"] = field(default_factory=list)

    # Used by process_event to suppress nested agent events in workflow mode
    entity_type: Literal["agent", "team", "workflow"] = "agent"
    # Leader/workflow name; member_name() compares against it to detect team members
    entity_name: str = ""

    # Last StepOutput content; WorkflowCompleted uses as fallback when content is None
    workflow_final_content: str = ""

    # Set by handlers on terminal events; router reads this for the final flush
    terminal_status: Optional[TaskStatus] = None

    def track_task(self, key: str, title: str) -> None:
        self.task_cards[key] = TaskCard(title=title)

    def complete_task(self, key: str) -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "complete"

    def error_task(self, key: str) -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "error"

    def resolve_all_pending(self, status: TaskStatus = "complete") -> List[TaskUpdateDict]:
        # Called at stream end to close any cards left in_progress (e.g. if the
        # model finished without emitting a ToolCallCompleted for every start).
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
        # Media can't be streamed inline — Slack requires a separate upload after
        # the stream ends. We collect here and upload_response_media() sends them.
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
