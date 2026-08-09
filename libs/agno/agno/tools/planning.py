"""
Planning tools for agent sessions.

Provides tools to manage goals, tasks, and decisions that persist in session_state.
Works standalone without a database - state lives in session_state.
"""

from dataclasses import dataclass, field
from datetime import datetime
from textwrap import dedent
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


@dataclass
class PlanningState:
    """Structured planning state for a session."""

    goal: Optional[str] = None
    goal_status: str = "pending"  # pending, in_progress, completed, failed
    tasks: List[Dict[str, Any]] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    next_step: Optional[str] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "goal_status": self.goal_status,
            "tasks": self.tasks,
            "decisions": self.decisions,
            "open_questions": self.open_questions,
            "next_step": self.next_step,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanningState":
        updated_at = data.get("updated_at")
        if updated_at and isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        return cls(
            goal=data.get("goal"),
            goal_status=data.get("goal_status", "pending"),
            tasks=data.get("tasks", []),
            decisions=data.get("decisions", []),
            open_questions=data.get("open_questions", []),
            next_step=data.get("next_step"),
            updated_at=updated_at,
        )

    def to_card(self, max_tasks: int = 5) -> str:
        """Render a compact planning state card for context injection."""
        lines = ["Current Planning State:"]

        if self.goal:
            lines.append(f"Goal: {self.goal} [{self.goal_status}]")

        if self.next_step:
            lines.append(f"Next step: {self.next_step}")

        if self.tasks:
            lines.append("Tasks:")
            for task in self.tasks[:max_tasks]:
                status = task.get("status", "pending")
                title = task.get("title", "Untitled")
                lines.append(f"  [{status}] {title}")
            if len(self.tasks) > max_tasks:
                lines.append(f"  ... and {len(self.tasks) - max_tasks} more")

        if self.open_questions:
            lines.append("Open questions:")
            for q in self.open_questions[:3]:
                lines.append(f"  - {q}")

        if self.decisions:
            recent = self.decisions[-2:]
            lines.append("Recent decisions:")
            for d in recent:
                lines.append(f"  - {d.get('decision', '')}")

        return "\n".join(lines)


PLANNING_STATE_KEY = "_planning"


class PlanningTools(Toolkit):
    """Tools for planning and task management in agent sessions.

    These tools help agents:
    - Set and track goals for the current session
    - Break work into tasks with status tracking
    - Record decisions and rationale
    - Maintain a clear next step
    - Surface planning state on demand

    State is stored in session_state and persists across runs.
    No database required - works standalone.
    """

    DEFAULT_INSTRUCTIONS = dedent("""\
        You have planning tools to stay organized during complex work:

        - `set_goal`: Set what you're trying to accomplish
        - `get_goal`: Check the current goal
        - `add_task`: Break work into trackable tasks
        - `update_task`: Update task status (pending/in_progress/done/failed)
        - `list_tasks`: See all tasks and their status
        - `add_decision`: Record a decision with rationale (prevents re-arguing)
        - `set_next_step`: Set what to do next
        - `get_planning_state`: Get full planning state card

        Use these tools to:
        - Start complex work by setting a goal and tasks
        - Track progress as you complete tasks
        - Record important decisions so you don't revisit them
        - Keep a clear next step to stay focused
        """)

    def __init__(
        self,
        enable_goal: bool = True,
        enable_tasks: bool = True,
        enable_decisions: bool = True,
        enable_next_step: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        """Initialize PlanningTools.

        Args:
            enable_goal: Enable goal management tools
            enable_tasks: Enable task management tools
            enable_decisions: Enable decision recording tools
            enable_next_step: Enable next step tracking
            instructions: Custom instructions (overrides default)
            add_instructions: Whether to add instructions to system prompt
        """
        self.instructions = instructions or self.DEFAULT_INSTRUCTIONS

        tools: List[Any] = []
        if enable_goal:
            tools.extend([self.set_goal, self.get_goal])
        if enable_tasks:
            tools.extend([self.add_task, self.update_task, self.list_tasks])
        if enable_decisions:
            tools.append(self.add_decision)
        if enable_next_step:
            tools.append(self.set_next_step)
        # Always include get_planning_state
        tools.append(self.get_planning_state)

        super().__init__(
            name="planning_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=tools,
            **kwargs,
        )

    def _get_state(self, run_context: RunContext) -> PlanningState:
        """Get or create planning state from session_state."""
        if run_context.session_state is None:
            run_context.session_state = {}

        data = run_context.session_state.get(PLANNING_STATE_KEY, {})
        return PlanningState.from_dict(data)

    def _save_state(self, run_context: RunContext, state: PlanningState) -> None:
        """Save planning state to session_state."""
        if run_context.session_state is None:
            run_context.session_state = {}

        state.updated_at = datetime.now()
        run_context.session_state[PLANNING_STATE_KEY] = state.to_dict()

    def set_goal(self, run_context: RunContext, goal: str) -> str:
        """Set or update the current goal you're working toward.

        Goals persist across runs and help maintain focus.

        Args:
            goal: Description of what you're trying to accomplish
        """
        try:
            state = self._get_state(run_context)
            state.goal = goal
            state.goal_status = "in_progress"
            self._save_state(run_context, state)
            log_debug(f"Goal set: {goal}")
            return f"Goal set: {goal}"
        except Exception as e:
            log_error(f"Error setting goal: {e}")
            return f"Error: {e}"

    def get_goal(self, run_context: RunContext) -> str:
        """Get the current goal and its status."""
        try:
            state = self._get_state(run_context)
            if state.goal:
                return f"Goal: {state.goal} [status: {state.goal_status}]"
            return "No goal set. Use set_goal to define what you're working toward."
        except Exception as e:
            log_error(f"Error getting goal: {e}")
            return f"Error: {e}"

    def add_task(
        self,
        run_context: RunContext,
        title: str,
        description: Optional[str] = None,
        priority: str = "normal",
    ) -> str:
        """Add a task to your plan.

        Tasks help break complex work into trackable pieces.

        Args:
            title: Short task title
            description: Optional detailed description
            priority: low, normal, or high
        """
        try:
            state = self._get_state(run_context)

            task = {
                "id": uuid4().hex[:8],
                "title": title,
                "description": description,
                "status": "pending",
                "priority": priority,
                "created_at": datetime.now().isoformat(),
            }
            state.tasks.append(task)
            self._save_state(run_context, state)

            log_debug(f"Task added: {title}")
            return f"Task added (#{len(state.tasks)}): {title}"
        except Exception as e:
            log_error(f"Error adding task: {e}")
            return f"Error: {e}"

    def update_task(
        self,
        run_context: RunContext,
        task_number: int,
        status: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> str:
        """Update a task's status or add notes.

        Args:
            task_number: Task number from list_tasks (1-indexed)
            status: New status (pending, in_progress, done, failed, blocked)
            notes: Optional notes to add
        """
        try:
            state = self._get_state(run_context)

            if not state.tasks:
                return "No tasks found."

            idx = task_number - 1
            if idx < 0 or idx >= len(state.tasks):
                return f"Invalid task number. Use 1-{len(state.tasks)}."

            task = state.tasks[idx]
            if status:
                task["status"] = status
            if notes:
                if "notes" not in task:
                    task["notes"] = []
                task["notes"].append(notes)
            task["updated_at"] = datetime.now().isoformat()

            self._save_state(run_context, state)
            log_debug(f"Task {task_number} updated")
            return f"Task {task_number} updated: {task['title']} [{task['status']}]"
        except Exception as e:
            log_error(f"Error updating task: {e}")
            return f"Error: {e}"

    def list_tasks(self, run_context: RunContext, status: Optional[str] = None) -> str:
        """List all tasks and their status.

        Args:
            status: Optional filter by status (pending, in_progress, done, failed, blocked)
        """
        try:
            state = self._get_state(run_context)

            if not state.tasks:
                return "No tasks found. Use add_task to create tasks."

            tasks = state.tasks
            if status:
                tasks = [t for t in tasks if t.get("status") == status]

            lines = ["Tasks:"]
            for i, t in enumerate(state.tasks, 1):
                task_status = t.get("status", "pending")
                priority = t.get("priority", "normal")
                marker = "[x]" if task_status == "done" else "[ ]"

                # Show if filtered out
                if status and t.get("status") != status:
                    continue

                lines.append(f"  {i}. {marker} [{priority}] {t['title']} ({task_status})")

            pending = sum(1 for t in state.tasks if t.get("status") not in ("done", "failed"))
            done = sum(1 for t in state.tasks if t.get("status") == "done")
            lines.append(f"\n{pending} pending, {done} done, {len(state.tasks)} total")

            return "\n".join(lines)
        except Exception as e:
            log_error(f"Error listing tasks: {e}")
            return f"Error: {e}"

    def add_decision(
        self,
        run_context: RunContext,
        decision: str,
        rationale: Optional[str] = None,
    ) -> str:
        """Record a decision with rationale.

        Use this to prevent re-arguing settled questions.

        Args:
            decision: What was decided
            rationale: Why this decision was made
        """
        try:
            state = self._get_state(run_context)

            entry = {
                "decision": decision,
                "rationale": rationale,
                "created_at": datetime.now().isoformat(),
            }
            state.decisions.append(entry)
            self._save_state(run_context, state)

            log_debug(f"Decision recorded: {decision}")
            return f"Decision recorded: {decision}"
        except Exception as e:
            log_error(f"Error recording decision: {e}")
            return f"Error: {e}"

    def set_next_step(self, run_context: RunContext, next_step: str) -> str:
        """Set what to do next.

        Helps maintain focus and continuity.

        Args:
            next_step: What should happen next
        """
        try:
            state = self._get_state(run_context)
            state.next_step = next_step
            self._save_state(run_context, state)

            log_debug(f"Next step set: {next_step}")
            return f"Next step: {next_step}"
        except Exception as e:
            log_error(f"Error setting next step: {e}")
            return f"Error: {e}"

    def get_planning_state(self, run_context: RunContext) -> str:
        """Get the full planning state card.

        Use this to recall your current goal, tasks, decisions, and next step.
        Call this when you feel uncertain about the current state of work.
        """
        try:
            state = self._get_state(run_context)

            if not state.goal and not state.tasks:
                return "No planning state set. Use set_goal and add_task to get started."

            return state.to_card(max_tasks=10)
        except Exception as e:
            log_error(f"Error getting planning state: {e}")
            return f"Error: {e}"


def get_planning_state_card(session_state: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract planning state card from session_state for context injection.

    Use this to inject planning state at run start or after compaction.

    Args:
        session_state: The session_state dict

    Returns:
        Planning state card string, or None if no planning state exists
    """
    if not session_state:
        return None

    data = session_state.get(PLANNING_STATE_KEY)
    if not data:
        return None

    state = PlanningState.from_dict(data)
    if not state.goal and not state.tasks:
        return None

    return state.to_card()
