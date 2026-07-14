"""Task model and TaskList for autonomous team execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional
from uuid import uuid4


class TaskStatus(str, Enum):
    """Status of a task in the team task list."""

    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"


@dataclass
class Task:
    """A single task in the team's shared task list."""

    id: str = ""
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.pending
    assignee: Optional[str] = None
    parent_id: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    result: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid4())[:8]
        if self.created_at == 0.0:
            self.created_at = time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "assignee": self.assignee,
            "parent_id": self.parent_id,
            "dependencies": self.dependencies,
            "result": self.result,
            "notes": self.notes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        status_value = data.get("status", "pending")
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=TaskStatus(status_value),
            assignee=data.get("assignee"),
            parent_id=data.get("parent_id"),
            dependencies=data.get("dependencies", []),
            result=data.get("result"),
            notes=data.get("notes", []),
            created_at=data.get("created_at", 0.0),
        )


TERMINAL_STATUSES = {TaskStatus.completed, TaskStatus.failed}
DEPENDENCY_SATISFIED_STATUSES = {TaskStatus.completed}


@dataclass
class TaskList:
    """A shared task list for autonomous team execution.

    Provides CRUD, dependency management, and serialization for tasks
    stored in session_state.
    """

    tasks: List[Task] = field(default_factory=list)
    goal_complete: bool = False
    completion_summary: Optional[str] = None

    # --- CRUD ---

    def create_task(
        self,
        title: str,
        description: str = "",
        assignee: Optional[str] = None,
        parent_id: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
    ) -> Task:
        task = Task(
            title=title,
            description=description,
            assignee=assignee,
            parent_id=parent_id,
            dependencies=dependencies or [],
        )
        self.tasks.append(task)
        self._update_blocked_statuses()
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def update_task(self, task_id: str, **updates: Any) -> Optional[Task]:
        task = self.get_task(task_id)
        if task is None:
            return None
        for key, value in updates.items():
            if key == "status" and isinstance(value, str):
                value = TaskStatus(value)
            if hasattr(task, key):
                setattr(task, key, value)
        self._update_blocked_statuses()
        return task

    # --- Queries ---

    def get_available_tasks(self, for_assignee: Optional[str] = None) -> List[Task]:
        """Return tasks that are pending and have all dependencies satisfied."""
        available = []
        for task in self.tasks:
            if task.status != TaskStatus.pending:
                continue
            if self._is_blocked(task):
                continue
            if for_assignee is not None and task.assignee is not None and task.assignee != for_assignee:
                continue
            available.append(task)
        return available

    def all_terminal(self) -> bool:
        """Return True when every task is in a terminal state (completed or failed)."""
        if not self.tasks:
            return False
        return all(t.status in TERMINAL_STATUSES for t in self.tasks)

    def get_summary_string(self) -> str:
        """Render the task list as a formatted string for the system message."""
        if not self.tasks:
            return "No tasks created yet."

        counts: Dict[str, int] = {}
        for t in self.tasks:
            counts[t.status.value] = counts.get(t.status.value, 0) + 1

        parts = [f"{v} {k}" for k, v in counts.items()]
        header = f"Tasks ({len(self.tasks)} total: {', '.join(parts)}):"

        lines = [header]
        for t in self.tasks:
            status_str = t.status.value.upper()
            assignee_str = f" (assigned: {t.assignee})" if t.assignee else " (unassigned)"
            lines.append(f"  [{t.id}] {t.title} - {status_str}{assignee_str}")
            if t.dependencies:
                lines.append(f"      Depends on: {t.dependencies}")
            if t.result:
                # Truncate long results
                result_preview = t.result[:200] + "..." if len(t.result) > 200 else t.result
                lines.append(f"      Result: {result_preview}")
            if t.notes:
                for note in t.notes[-3:]:  # Show last 3 notes
                    lines.append(f"      Note: {note}")

        if self.goal_complete and self.completion_summary:
            lines.append(f"\nGoal marked complete: {self.completion_summary}")

        return "\n".join(lines)

    # --- Dependency management ---

    def _is_blocked(self, task: Task) -> bool:
        """Check if a task has unfinished or failed dependencies."""
        if not task.dependencies:
            return False
        for dep_id in task.dependencies:
            dep = self.get_task(dep_id)
            if dep is None:
                return True  # Unknown dependency ID -- treat as blocked (fail-closed)
            if dep.status not in DEPENDENCY_SATISFIED_STATUSES:
                return True
        return False

    def _has_failed_dependency(self, task: "Task") -> bool:
        """Return True if any dependency of *task* has failed."""
        if not task.dependencies:
            return False
        for dep_id in task.dependencies:
            dep = self.get_task(dep_id)
            if dep is not None and dep.status == TaskStatus.failed:
                return True
        return False

    def _update_blocked_statuses(self) -> None:
        """Recompute blocked status for all pending/blocked tasks.

        If a dependency has failed the dependent task is also marked failed
        so that ``all_terminal()`` can detect completion and the loop does
        not deadlock.
        """
        for task in self.tasks:
            if task.status == TaskStatus.blocked:
                if self._has_failed_dependency(task):
                    task.status = TaskStatus.failed
                    task.result = "Automatically failed: a dependency failed."
                elif not self._is_blocked(task):
                    task.status = TaskStatus.pending
            elif task.status == TaskStatus.pending:
                if self._is_blocked(task):
                    task.status = TaskStatus.blocked

    # --- Serialization ---

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "goal_complete": self.goal_complete,
            "completion_summary": self.completion_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskList":
        tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        task_list = cls(
            tasks=tasks,
            goal_complete=data.get("goal_complete", False),
            completion_summary=data.get("completion_summary"),
        )
        task_list._update_blocked_statuses()
        return task_list


# --- session_state helpers ---

TASK_LIST_KEY = "_team_tasks"


def load_task_list(session_state: Optional[Dict[str, Any]]) -> TaskList:
    """Load task list from session_state, or return an empty one."""
    if session_state and TASK_LIST_KEY in session_state:
        return TaskList.from_dict(session_state[TASK_LIST_KEY])
    return TaskList()


def save_task_list(session_state: Optional[Dict[str, Any]], task_list: TaskList) -> None:
    """Persist task list into session_state."""
    if session_state is not None:
        session_state[TASK_LIST_KEY] = task_list.to_dict()
