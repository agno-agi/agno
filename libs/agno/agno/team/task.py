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
    cancelled = "cancelled"
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


TERMINAL_STATUSES = {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}
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

    def _invalidate_goal_completion(self) -> None:
        """Clear a completion marker when the active plan changes."""
        self.goal_complete = False
        self.completion_summary = None

    def create_task(
        self,
        title: str,
        description: str = "",
        assignee: Optional[str] = None,
        parent_id: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
    ) -> Task:
        # A newly-created task starts a new unit of work, so a completion
        # marker inherited from an earlier run is no longer valid.
        self._invalidate_goal_completion()
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
        previous_status = task.status
        requested_status = updates.get("status")
        if isinstance(requested_status, str):
            requested_status = TaskStatus(requested_status)
        if (
            previous_status == TaskStatus.cancelled
            and requested_status is not None
            and requested_status != TaskStatus.cancelled
        ):
            raise ValueError("Cancelled tasks cannot be reopened.")
        prospective_status = requested_status if requested_status is not None else previous_status
        prospective_dependencies = updates.get("dependencies", task.dependencies)
        requires_satisfied_dependencies = requested_status in (
            TaskStatus.pending,
            TaskStatus.in_progress,
            TaskStatus.completed,
        ) or ("dependencies" in updates and prospective_status in (TaskStatus.in_progress, TaskStatus.completed))
        if requires_satisfied_dependencies and self._is_blocked(task, dependencies=prospective_dependencies):
            raise ValueError("Tasks with unresolved dependencies cannot be started or completed.")
        if (
            requested_status is not None
            and requested_status != previous_status
            and previous_status in TERMINAL_STATUSES
            and "result" not in updates
        ):
            updates["result"] = None
        if (
            requested_status is not None
            and requested_status != previous_status
            and requested_status != TaskStatus.completed
        ):
            self._invalidate_goal_completion()
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
        """Return True when every task is completed, failed, or cancelled."""
        if not self.tasks:
            return False
        return all(t.status in TERMINAL_STATUSES for t in self.tasks)

    def all_completed(self) -> bool:
        """Return True when every task completed successfully."""
        if not self.tasks:
            return False
        return all(t.status == TaskStatus.completed for t in self.tasks)

    def get_summary_string(self, result_limit: int = 200) -> str:
        """Render the task list as a formatted string for the system message.

        Args:
            result_limit: Maximum character length for task result previews; 0 disables previews.
        """
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
            if t.result and result_limit > 0:
                result_preview = t.result[:result_limit] + "..." if len(t.result) > result_limit else t.result
                lines.append(f"      Result: {result_preview}")
            if t.notes:
                for note in t.notes[-3:]:  # Show last 3 notes
                    lines.append(f"      Note: {note}")

        if self.goal_complete and self.completion_summary:
            lines.append(f"\nGoal marked complete: {self.completion_summary}")

        return "\n".join(lines)

    # --- Dependency management ---

    def _is_blocked(self, task: Task, dependencies: Optional[List[str]] = None) -> bool:
        """Check if a task has unfinished or failed dependencies."""
        dependency_ids = task.dependencies if dependencies is None else dependencies
        if not dependency_ids:
            return False
        for dep_id in dependency_ids:
            if dep_id == task.id:
                return True
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

    def _has_cancelled_dependency(self, task: "Task") -> bool:
        """Return True if any dependency of *task* was cancelled."""
        if not task.dependencies:
            return False
        for dep_id in task.dependencies:
            dep = self.get_task(dep_id)
            if dep is not None and dep.status == TaskStatus.cancelled:
                return True
        return False

    def _update_blocked_statuses(self) -> None:
        """Recompute blocked status for all pending/blocked tasks.

        Failed dependencies fail their dependents; cancelled dependencies
        cancel theirs. This lets ``all_terminal()`` detect completion without
        treating intentional replanning as an execution failure.
        """
        changed = True
        while changed:
            changed = False
            for task in self.tasks:
                if task.status not in (TaskStatus.pending, TaskStatus.blocked):
                    continue

                new_status: TaskStatus = task.status
                new_result = task.result
                if self._has_failed_dependency(task):
                    new_status = TaskStatus.failed
                    if new_result is None:
                        new_result = "Automatically failed: a dependency failed."
                elif self._has_cancelled_dependency(task):
                    new_status = TaskStatus.cancelled
                    if new_result is None:
                        new_result = "Automatically cancelled: a dependency was cancelled."
                elif self._is_blocked(task):
                    new_status = TaskStatus.blocked
                else:
                    new_status = TaskStatus.pending

                if task.status != new_status or task.result != new_result:
                    task.status = new_status
                    task.result = new_result
                    changed = True

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
