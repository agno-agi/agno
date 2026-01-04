"""
Custom Learning Store
===========================================
Build your own learning type by implementing the LearningStore protocol.

Use cases:
- Project-specific context (beyond sessions)
- Domain-specific knowledge structures
- Integration with external systems
- Custom retrieval patterns

This cookbook implements a ProjectStore that tracks project-level
information across sessions and users.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine
from agno.models.openai import OpenAIChat


# =============================================================================
# Custom Schema: Project
# =============================================================================
@dataclass
class Project:
    """Schema for project-level context."""

    project_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    status: str = "active"  # active, paused, completed
    tech_stack: List[str] = field(default_factory=list)
    team_members: List[str] = field(default_factory=list)
    milestones: List[Dict[str, Any]] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "tech_stack": self.tech_stack,
            "team_members": self.team_members,
            "milestones": self.milestones,
            "decisions": self.decisions,
            "blockers": self.blockers,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Project"]:
        if not isinstance(data, dict):
            return None
        try:
            valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            return cls(**filtered)
        except Exception:
            return None

    def get_context_text(self) -> str:
        """Format for agent context."""
        parts = []
        if self.name:
            parts.append(f"Project: {self.name}")
        if self.description:
            parts.append(f"Description: {self.description}")
        if self.status:
            parts.append(f"Status: {self.status}")
        if self.tech_stack:
            parts.append(f"Tech Stack: {', '.join(self.tech_stack)}")
        if self.team_members:
            parts.append(f"Team: {', '.join(self.team_members)}")
        if self.blockers:
            parts.append(f"Blockers: {', '.join(self.blockers)}")
        if self.decisions:
            recent = self.decisions[-3:]
            decisions_text = "\n".join(f"  - {d.get('decision', d)}" for d in recent)
            parts.append(f"Recent Decisions:\n{decisions_text}")
        return "\n".join(parts)


# =============================================================================
# Custom Store: ProjectStore
# =============================================================================
@dataclass
class ProjectStore:
    """Custom learning store for project-level context.

    Implements the LearningStore protocol.
    """

    db: Any = None
    _cache: Dict[str, Project] = field(default_factory=dict)
    _updated: bool = field(default=False, init=False)

    # =========================================================================
    # LearningStore Protocol Implementation
    # =========================================================================

    @property
    def learning_type(self) -> str:
        """Unique identifier for this store."""
        return "project"

    @property
    def schema(self) -> Any:
        """Schema class used by this store."""
        return Project

    def recall(self, project_id: str = None, **kwargs) -> Optional[Project]:
        """Retrieve project by project_id."""
        if not project_id:
            return None

        # Check cache first
        if project_id in self._cache:
            return self._cache[project_id]

        # Try database
        if self.db:
            try:
                result = self.db.get_learning(
                    learning_type=self.learning_type,
                    session_id=project_id,  # Reuse session_id column for project_id
                )
                if result and result.get("content"):
                    project = Project.from_dict(result["content"])
                    if project:
                        self._cache[project_id] = project
                        return project
            except Exception:
                pass
        return None

    async def arecall(self, project_id: str = None, **kwargs) -> Optional[Project]:
        """Async version of recall."""
        return self.recall(project_id=project_id, **kwargs)

    def process(self, messages: List[Any], project_id: str = None, **kwargs) -> None:
        """Extract project info from messages.

        For simplicity, this doesn't do automatic extraction.
        Project updates happen via the tool.
        """
        pass

    async def aprocess(
        self, messages: List[Any], project_id: str = None, **kwargs
    ) -> None:
        """Async version of process."""
        pass

    def build_context(self, data: Any) -> str:
        """Build context string for agent's system prompt."""
        if not data:
            return ""
        return f"<project_context>\n{data.get_context_text()}\n</project_context>"

    def get_tools(self, project_id: str = None, **kwargs) -> List[Callable]:
        """Get tools for agent to update project."""
        if not project_id:
            return []

        def update_project(
            name: Optional[str] = None,
            description: Optional[str] = None,
            status: Optional[str] = None,
            add_tech: Optional[str] = None,
            add_member: Optional[str] = None,
            add_blocker: Optional[str] = None,
            remove_blocker: Optional[str] = None,
            add_decision: Optional[str] = None,
            add_note: Optional[str] = None,
        ) -> str:
            """Update project information.

            Args:
                name: Set project name
                description: Set project description
                status: Set status (active/paused/completed)
                add_tech: Add technology to stack
                add_member: Add team member
                add_blocker: Add a blocker
                remove_blocker: Remove a resolved blocker
                add_decision: Record a decision made
                add_note: Add a project note
            """
            project = self.recall(project_id=project_id) or Project(
                project_id=project_id
            )

            changes = []
            if name:
                project.name = name
                changes.append(f"name={name}")
            if description:
                project.description = description
                changes.append("description updated")
            if status:
                project.status = status
                changes.append(f"status={status}")
            if add_tech and add_tech not in project.tech_stack:
                project.tech_stack.append(add_tech)
                changes.append(f"added tech: {add_tech}")
            if add_member and add_member not in project.team_members:
                project.team_members.append(add_member)
                changes.append(f"added member: {add_member}")
            if add_blocker:
                project.blockers.append(add_blocker)
                changes.append(f"added blocker")
            if remove_blocker and remove_blocker in project.blockers:
                project.blockers.remove(remove_blocker)
                changes.append(f"removed blocker")
            if add_decision:
                project.decisions.append({"decision": add_decision})
                changes.append("recorded decision")
            if add_note:
                project.notes.append(add_note)
                changes.append("added note")

            self._save(project_id=project_id, project=project)
            return f"Project updated: {', '.join(changes)}" if changes else "No changes"

        return [update_project]

    async def aget_tools(self, **kwargs) -> List[Callable]:
        """Async version of get_tools."""
        return self.get_tools(**kwargs)

    @property
    def was_updated(self) -> bool:
        """Check if store was updated."""
        return self._updated

    # =========================================================================
    # Additional Methods
    # =========================================================================

    def _save(self, project_id: str, project: Project) -> None:
        """Save project to cache and database."""
        self._cache[project_id] = project
        self._updated = True

        if self.db:
            try:
                self.db.upsert_learning(
                    id=f"project_{project_id}",
                    learning_type=self.learning_type,
                    session_id=project_id,
                    content=project.to_dict(),
                )
            except Exception as e:
                print(f"Warning: Failed to save project to DB: {e}")

    def get(self, project_id: str) -> Optional[Project]:
        """Convenience method to get a project."""
        return self.recall(project_id=project_id)

    def list_projects(self) -> List[str]:
        """List all cached project IDs."""
        return list(self._cache.keys())

    def __repr__(self) -> str:
        return f"ProjectStore(cached={len(self._cache)})"


# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Create custom store
project_store = ProjectStore(db=db)

# =============================================================================
# Create Agent with Custom Store
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        user_profile=True,
        custom_stores={
            "project": project_store,  # Register custom store!
        },
    ),
    markdown=True,
)


# =============================================================================
# Helper
# =============================================================================
def show_project(project_id: str):
    """Display project info."""
    project = agent.learning.stores["project"].get(project_id=project_id)
    if project:
        print(f"\n🏗️ Project: {project.name or project_id}")
        print(f"   Status: {project.status}")
        if project.tech_stack:
            print(f"   Tech: {', '.join(project.tech_stack)}")
        if project.team_members:
            print(f"   Team: {', '.join(project.team_members)}")
        if project.blockers:
            print(f"   Blockers: {', '.join(project.blockers)}")
        if project.decisions:
            print(f"   Decisions: {len(project.decisions)}")
    else:
        print(f"\n🏗️ Project {project_id}: Not found")
    print()


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    project_id = "phoenix"

    # --- Initialize project ---
    print("=" * 60)
    print("Initialize Project")
    print("=" * 60)
    agent.print_response(
        "Let's start tracking Project Phoenix. It's a mobile app for fitness "
        "tracking. We're using React Native, Node.js, and PostgreSQL. "
        "Team members are Alice (frontend), Bob (backend), and Carol (design).",
        user_id="pm@company.com",
        session_id=project_id,
        stream=True,
    )
    show_project(project_id)

    # --- Add blocker ---
    print("=" * 60)
    print("Add Blocker")
    print("=" * 60)
    agent.print_response(
        "We're blocked on the Apple Developer account - waiting for approval.",
        user_id="pm@company.com",
        session_id=project_id,
        stream=True,
    )
    show_project(project_id)

    # --- Record decision ---
    print("=" * 60)
    print("Record Decision")
    print("=" * 60)
    agent.print_response(
        "We decided to use Firebase for push notifications instead of building our own.",
        user_id="bob@company.com",
        session_id=project_id,
        stream=True,
    )
    show_project(project_id)

    # --- Different user, same project ---
    print("=" * 60)
    print("Different User Gets Context")
    print("=" * 60)
    agent.print_response(
        "I just joined the project. Can you catch me up?",
        user_id="dave@company.com",  # New team member
        session_id=project_id,
        stream=True,
    )

    # --- Show registered stores ---
    print("=" * 60)
    print("Registered Stores")
    print("=" * 60)
    for name, store in agent.learning.stores.items():
        print(f"  {name}: {store}")
