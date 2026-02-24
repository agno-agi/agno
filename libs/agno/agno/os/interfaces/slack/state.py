from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Literal

if TYPE_CHECKING:
    from agno.run.base import BaseRunOutputEvent

TaskStatus = Literal["in_progress", "complete", "error"]


@dataclass
class TaskCard:
    title: str
    status: TaskStatus = "in_progress"


@dataclass
class StreamState:
    title_set: bool = False
    error_count: int = 0

    text_buffer: str = ""

    reasoning_round: int = 0

    progress_started: bool = False
    task_cards: Dict[str, TaskCard] = field(default_factory=dict)

    images: list = field(default_factory=list)
    videos: list = field(default_factory=list)
    audio: list = field(default_factory=list)
    files: list = field(default_factory=list)

    # Used by router to select DISPATCH (agent/team) vs WORKFLOW_DISPATCH (workflow)
    entity_type: Literal["agent", "team", "workflow"] = "agent"
    entity_name: str = ""

    workflow_final_content: str = ""

    # Set by handlers on terminal events; router reads this for the final flush
    terminal_status: str = ""

    def track_task(self, key: str, title: str) -> None:
        self.task_cards[key] = TaskCard(title=title)
        self.progress_started = True

    def complete_task(self, key: str) -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "complete"

    def error_task(self, key: str) -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "error"

    def resolve_all_pending(self, status: str = "complete") -> List[dict]:
        # Called at stream end to close any cards left in_progress (e.g. if the
        # model finished without emitting a ToolCallCompleted for every start).
        chunks: List[dict] = []
        for key, card in self.task_cards.items():
            if card.status == "in_progress":
                card.status = status  # type: ignore[assignment]
                chunks.append({"type": "task_update", "id": key, "title": card.title, "status": status})
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
