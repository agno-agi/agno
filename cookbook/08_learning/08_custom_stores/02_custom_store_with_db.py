"""
Custom Store: Database-Backed Example
======================================
Shows how to create a custom learning store with database persistence.

This example demonstrates:
- Using the database's learning methods (get_learning, upsert_learning)
- Namespacing data by project_id
- Model-based extraction from conversations
- Exposing tools to the agent

For a simpler in-memory example, see 01_minimal_custom_store.py
"""

from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine
from agno.models.openai import OpenAIResponses

try:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.models.base import Model
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class ProjectNotes:
    """Schema for project notes."""

    summary: Optional[str] = None
    goals: Optional[List[str]] = None
    blockers: Optional[List[str]] = None
    decisions: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Custom Store Implementation
# ---------------------------------------------------------------------------


@dataclass
class ProjectNotesStore:
    """Custom store for project notes with database persistence.

    Stores structured notes about a project including goals,
    blockers, and decisions.
    """

    # Database for persistence
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None

    # Model for extraction (optional - for ALWAYS mode)
    model: Optional["Model"] = None

    # Custom context
    context: Dict[str, Any] = field(default_factory=dict)

    # Enable agent tools
    enable_tools: bool = True

    # Internal state
    _updated: bool = field(default=False, init=False)

    # =========================================================================
    # LearningStore Protocol Implementation
    # =========================================================================

    @property
    def learning_type(self) -> str:
        """Unique identifier for this learning type."""
        return "project_notes"

    @property
    def schema(self) -> Any:
        """Schema class used for this learning type."""
        return ProjectNotes

    def recall(self, **kwargs) -> Optional[ProjectNotes]:
        """Retrieve project notes from database."""
        if not self.db:
            return None

        project_id = self.context.get("project_id")
        if not project_id:
            return None

        try:
            result = self.db.get_learning(
                learning_type=self.learning_type,
                namespace=project_id,  # Use project_id as namespace
            )

            if result and result.get("content"):
                content = result["content"]
                return ProjectNotes(
                    summary=content.get("summary"),
                    goals=content.get("goals"),
                    blockers=content.get("blockers"),
                    decisions=content.get("decisions"),
                )
            return None

        except Exception as e:
            print(f"Error retrieving project notes: {e}")
            return None

    async def arecall(self, **kwargs) -> Optional[ProjectNotes]:
        """Async version of recall."""
        if not self.db:
            return None

        project_id = self.context.get("project_id")
        if not project_id:
            return None

        try:
            result = await self.db.get_learning(
                learning_type=self.learning_type,
                namespace=project_id,
            )

            if result and result.get("content"):
                content = result["content"]
                return ProjectNotes(
                    summary=content.get("summary"),
                    goals=content.get("goals"),
                    blockers=content.get("blockers"),
                    decisions=content.get("decisions"),
                )
            return None

        except Exception as e:
            print(f"Error retrieving project notes: {e}")
            return None

    def process(self, messages: List[Any], **kwargs) -> None:
        """Extract project notes from messages.

        This is called automatically after conversations when using
        LearningMachine. For this example, we skip automatic extraction
        and rely on the agent tools instead.
        """
        # Skip automatic extraction - use tools instead
        pass

    async def aprocess(self, messages: List[Any], **kwargs) -> None:
        """Async version of process."""
        pass

    def build_context(self, data: Any) -> str:
        """Build context string for agent prompts."""
        project_id = self.context.get("project_id", "unknown")

        if not data:
            context = dedent(f"""\
                <project_notes>
                Project: {project_id}
                No notes saved yet.
                """)
            if self.enable_tools:
                context += dedent("""
                Use the add_project_note tool to save important project information.
                """)
            context += "</project_notes>"
            return context

        lines = ["<project_notes>", f"Project: {project_id}"]

        if data.summary:
            lines.append(f"\nSummary: {data.summary}")

        if data.goals:
            lines.append("\nGoals:")
            for goal in data.goals:
                lines.append(f"  - {goal}")

        if data.blockers:
            lines.append("\nBlockers:")
            for blocker in data.blockers:
                lines.append(f"  - {blocker}")

        if data.decisions:
            lines.append("\nDecisions:")
            for decision in data.decisions:
                lines.append(f"  - {decision}")

        if self.enable_tools:
            lines.append(
                dedent("""
                <note_tools>
                Use add_project_note to save new goals, blockers, or decisions.
                Use update_project_summary to update the project summary.
                </note_tools>""")
            )

        lines.append("</project_notes>")
        return "\n".join(lines)

    def get_tools(self, **kwargs) -> List[Callable]:
        """Get tools to expose to the agent."""
        if not self.enable_tools:
            return []

        tools = []

        def add_project_note(
            note_type: str,
            content: str,
        ) -> str:
            """Add a note to the project.

            Args:
                note_type: Type of note - one of 'goal', 'blocker', 'decision'
                content: The note content
            """
            if note_type not in ["goal", "blocker", "decision"]:
                return f"Invalid note_type: {note_type}. Must be goal, blocker, or decision."

            current = self.recall() or ProjectNotes()

            if note_type == "goal":
                current.goals = current.goals or []
                current.goals.append(content)
            elif note_type == "blocker":
                current.blockers = current.blockers or []
                current.blockers.append(content)
            elif note_type == "decision":
                current.decisions = current.decisions or []
                current.decisions.append(content)

            self._save(current)
            return f"Added {note_type}: {content}"

        def update_project_summary(summary: str) -> str:
            """Update the project summary.

            Args:
                summary: Brief summary of the project
            """
            current = self.recall() or ProjectNotes()
            current.summary = summary
            self._save(current)
            return "Updated project summary."

        tools.append(add_project_note)
        tools.append(update_project_summary)

        return tools

    async def aget_tools(self, **kwargs) -> List[Callable]:
        """Async version of get_tools."""
        return self.get_tools(**kwargs)

    @property
    def was_updated(self) -> bool:
        """Check if store was updated in last operation."""
        return self._updated

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _save(self, notes: ProjectNotes) -> None:
        """Save project notes to database."""
        if not self.db:
            return

        project_id = self.context.get("project_id")
        if not project_id:
            return

        content = {
            "summary": notes.summary,
            "goals": notes.goals,
            "blockers": notes.blockers,
            "decisions": notes.decisions,
        }

        try:
            self.db.upsert_learning(
                id=f"project_notes:{project_id}",
                learning_type=self.learning_type,
                namespace=project_id,
                content=content,
            )
            self._updated = True
        except Exception as e:
            print(f"Error saving project notes: {e}")

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def print(self) -> None:
        """Print current project notes."""
        project_id = self.context.get("project_id", "unknown")
        data = self.recall()

        print(f"\n--- Project Notes: {project_id} ---")
        if not data:
            print("  (no notes)")
        else:
            if data.summary:
                print(f"  Summary: {data.summary}")
            if data.goals:
                print("  Goals:")
                for goal in data.goals:
                    print(f"    - {goal}")
            if data.blockers:
                print("  Blockers:")
                for blocker in data.blockers:
                    print(f"    - {blocker}")
            if data.decisions:
                print("  Decisions:")
                for decision in data.decisions:
                    print(f"    - {decision}")
        print()


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Create custom store with DB and project context
project_notes_store = ProjectNotesStore(
    db=db,
    context={
        "project_id": "learning-machine",
    },
    enable_tools=True,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=LearningMachine(
        custom_stores={
            "project_notes": project_notes_store,
        },
    ),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "developer@example.com"

    print("\n" + "=" * 60)
    print("Custom Store Demo: Project Notes with Database")
    print("=" * 60 + "\n")

    # First interaction - agent sees tools
    agent.print_response(
        "I'm working on the learning machine project. Our main goal is to "
        "create a unified learning system for agents. Can you note that down?",
        user_id=user_id,
        stream=True,
    )

    project_notes_store.print()

    # Second interaction - add a blocker
    print("\n" + "=" * 60)
    print("Adding a blocker")
    print("=" * 60 + "\n")

    agent.print_response(
        "We have a blocker - the custom store context propagation isn't implemented yet.",
        user_id=user_id,
        stream=True,
    )

    project_notes_store.print()

    # Third interaction - verify persistence
    print("\n" + "=" * 60)
    print("New session - data persisted")
    print("=" * 60 + "\n")

    agent.print_response(
        "What are our current project notes?",
        user_id=user_id,
        session_id="new_session",
        stream=True,
    )

    project_notes_store.print()
