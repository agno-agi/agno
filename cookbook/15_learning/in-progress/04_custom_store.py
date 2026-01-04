"""
Advanced: Custom Learning Store
===============================
Implement the LearningStore protocol for custom learning types.

LearningMachine is extensible. You can create custom stores for
domain-specific learning types not covered by the built-in stores.

The protocol requires:
- learning_type: Unique identifier
- schema: Data structure class
- recall(): Retrieve learnings
- process(): Extract and save learnings
- build_context(): Format for system prompt
- get_tools(): Agent tools (optional)
- was_updated: Track if store was modified

Run:
    python cookbook/15_learning/advanced/04_custom_store.py
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")


# ============================================================================
# Custom Schema: Project Context
# ============================================================================
@dataclass
class ProjectContext:
    """Schema for tracking project-specific context."""

    project_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None  # active, paused, complete
    tech_stack: Optional[List[str]] = field(default_factory=list)
    team_members: Optional[List[str]] = field(default_factory=list)
    milestones: Optional[List[Dict[str, str]]] = field(default_factory=list)
    notes: Optional[List[str]] = field(default_factory=list)
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "tech_stack": self.tech_stack,
            "team_members": self.team_members,
            "milestones": self.milestones,
            "notes": self.notes,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectContext":
        return cls(
            project_id=data["project_id"],
            name=data.get("name"),
            description=data.get("description"),
            status=data.get("status"),
            tech_stack=data.get("tech_stack", []),
            team_members=data.get("team_members", []),
            milestones=data.get("milestones", []),
            notes=data.get("notes", []),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
        )


# ============================================================================
# Custom Config
# ============================================================================
@dataclass
class ProjectContextConfig:
    """Configuration for ProjectContextStore."""

    enable_agent_tools: bool = True


# ============================================================================
# Custom Learning Store: ProjectContextStore
# ============================================================================
@dataclass
class ProjectContextStore:
    """
    Custom learning store for project-specific context.
    
    Implements the LearningStore protocol.
    """

    config: ProjectContextConfig = field(default_factory=ProjectContextConfig)
    _storage: Dict[str, ProjectContext] = field(default_factory=dict, init=False)
    _updated: bool = field(default=False, init=False)

    @property
    def learning_type(self) -> str:
        """Unique identifier for this store."""
        return "project_context"

    @property
    def schema(self) -> Any:
        """Schema class used by this store."""
        return ProjectContext

    def recall(self, project_id: str, **kwargs) -> Optional[ProjectContext]:
        """Retrieve project context by ID."""
        return self._storage.get(project_id)

    async def arecall(self, project_id: str, **kwargs) -> Optional[ProjectContext]:
        """Async version of recall."""
        return self.recall(project_id=project_id, **kwargs)

    def process(self, messages: List[Any], project_id: str, **kwargs) -> None:
        """
        Extract and save project context from messages.
        
        In a real implementation, this would:
        1. Parse messages for project-related info
        2. Update the project context
        3. Persist to database
        """
        # Simplified: Just mark as processed
        if project_id in self._storage:
            self._storage[project_id].updated_at = datetime.now()
            self._updated = True

    async def aprocess(self, messages: List[Any], project_id: str, **kwargs) -> None:
        """Async version of process."""
        self.process(messages=messages, project_id=project_id, **kwargs)

    def build_context(self, data: Optional[ProjectContext]) -> str:
        """Build context string for system prompt."""
        if not data:
            return ""

        parts = [f"<project_context project_id='{data.project_id}'>"]
        
        if data.name:
            parts.append(f"Project: {data.name}")
        if data.description:
            parts.append(f"Description: {data.description}")
        if data.status:
            parts.append(f"Status: {data.status}")
        if data.tech_stack:
            parts.append(f"Tech Stack: {', '.join(data.tech_stack)}")
        if data.team_members:
            parts.append(f"Team: {', '.join(data.team_members)}")
        if data.milestones:
            parts.append("Milestones:")
            for m in data.milestones:
                parts.append(f"  - {m.get('name', 'Unknown')}: {m.get('status', 'pending')}")
        if data.notes:
            parts.append("Notes:")
            for note in data.notes[-5:]:  # Last 5 notes
                parts.append(f"  - {note}")

        parts.append("</project_context>")
        return "\n".join(parts)

    def get_tools(self, project_id: str, **kwargs) -> List[Callable]:
        """Get tools for agent interaction."""
        if not self.config.enable_agent_tools:
            return []

        def update_project(
            name: Optional[str] = None,
            description: Optional[str] = None,
            status: Optional[str] = None,
            add_tech: Optional[str] = None,
            add_member: Optional[str] = None,
            add_note: Optional[str] = None,
        ) -> str:
            """Update project context."""
            if project_id not in self._storage:
                self._storage[project_id] = ProjectContext(project_id=project_id)
            
            ctx = self._storage[project_id]
            
            if name:
                ctx.name = name
            if description:
                ctx.description = description
            if status:
                ctx.status = status
            if add_tech:
                ctx.tech_stack.append(add_tech)
            if add_member:
                ctx.team_members.append(add_member)
            if add_note:
                ctx.notes.append(add_note)
            
            ctx.updated_at = datetime.now()
            self._updated = True
            
            return f"Updated project {project_id}"

        return [update_project]

    async def aget_tools(self, **kwargs) -> List[Callable]:
        """Async version of get_tools."""
        return self.get_tools(**kwargs)

    @property
    def was_updated(self) -> bool:
        """Check if store was updated in last operation."""
        return self._updated


# ============================================================================
# Agent with Custom Store
# ============================================================================
project_store = ProjectContextStore()

agent = Agent(
    name="Project Context Agent",
    model=model,
    db=db,
    instructions="""\
You help manage project context and information.

When users discuss projects:
- Track project details (name, description, status)
- Record tech stack and team members
- Log important notes and milestones

Use the update_project tool to save project information.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(mode="background"),
        custom_stores={
            "project": project_store,
        },
    ),
    markdown=True,
)


# ============================================================================
# Demo
# ============================================================================
def demo():
    """Demonstrate custom store usage."""
    print("=" * 60)
    print("Custom Learning Store Demo")
    print("=" * 60)

    user = "dev@company.com"
    project_id = "project_phoenix"

    # Create project context
    print("\n--- Setup Project ---\n")
    
    # Manually set up project for demo
    project_store._storage[project_id] = ProjectContext(
        project_id=project_id,
        name="Project Phoenix",
        description="Next-gen API platform",
        status="active",
        tech_stack=["Python", "FastAPI", "PostgreSQL"],
        team_members=["Alice", "Bob"],
        notes=["Kicked off Jan 15", "MVP target: March 1"],
        updated_at=datetime.now(),
    )

    # Query project context
    print("\n--- Query Project ---\n")
    ctx = project_store.recall(project_id=project_id)
    if ctx:
        print("Retrieved context:")
        print(project_store.build_context(ctx))

    # Interact with agent
    print("\n--- Agent Interaction ---\n")
    agent.print_response(
        "Add a note: Carol joined the team as frontend lead",
        user_id=user,
        session_id="project_session",
        stream=True,
    )


# ============================================================================
# Protocol Reference
# ============================================================================
def protocol_reference():
    """Print the LearningStore protocol reference."""
    print("\n" + "=" * 60)
    print("LearningStore Protocol Reference")
    print("=" * 60)
    print("""
@runtime_checkable
class LearningStore(Protocol):
    
    @property
    def learning_type(self) -> str:
        '''Unique identifier (e.g., 'project_context').'''
        ...

    @property
    def schema(self) -> Any:
        '''Schema class this store uses.'''
        ...

    def recall(self, **context) -> Optional[Any]:
        '''Retrieve learnings from storage.'''
        ...

    async def arecall(self, **context) -> Optional[Any]:
        '''Async version of recall.'''
        ...

    def process(self, messages: List[Any], **context) -> None:
        '''Extract and save learnings to storage.'''
        ...

    async def aprocess(self, messages: List[Any], **context) -> None:
        '''Async version of process.'''
        ...

    def build_context(self, data: Any) -> str:
        '''Build context string for agent's system prompt.'''
        ...

    def get_tools(self, **context) -> List[Callable]:
        '''Get tools to expose to agent.'''
        ...

    async def aget_tools(self, **context) -> List[Callable]:
        '''Async version of get_tools.'''
        ...

    @property
    def was_updated(self) -> bool:
        '''Check if store was updated in last operation.'''
        ...
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    protocol_reference()
    demo()

    print("\n" + "=" * 60)
    print("✅ Custom stores extend LearningMachine")
    print("   Implement the LearningStore protocol")
    print("   Register via custom_stores={...}")
    print("=" * 60)
