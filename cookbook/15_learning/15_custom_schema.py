"""
Custom Schemas
===========================================
Customize the data structures used by learning stores.

Use cases:
- Add fields specific to your domain
- Change how data is formatted
- Add validation logic
- Integrate with existing data models

This cookbook shows how to create custom schemas for:
- UserProfile
- SessionContext
- LearnedKnowledge
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    LearningMachine,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat

# =============================================================================
# Custom User Profile Schema
# =============================================================================
@dataclass
class EnterpriseUserProfile:
    """Custom user profile with enterprise-specific fields."""

    user_id: str
    # Standard fields
    name: Optional[str] = None
    email: Optional[str] = None
    memories: List[Dict[str, Any]] = field(default_factory=list)

    # Enterprise-specific fields
    department: Optional[str] = None
    role: Optional[str] = None
    permissions: List[str] = field(default_factory=list)
    projects: List[str] = field(default_factory=list)
    expertise_areas: List[str] = field(default_factory=list)
    communication_preference: Optional[str] = None  # "brief", "detailed", "technical"
    timezone: Optional[str] = None

    # Metadata
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["EnterpriseUserProfile"]:
        """Parse from dict. Returns None on failure."""
        if not isinstance(data, dict):
            return None
        try:
            valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            return cls(**filtered)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "user_id": self.user_id,
            "name": self.name,
            "email": self.email,
            "memories": self.memories,
            "department": self.department,
            "role": self.role,
            "permissions": self.permissions,
            "projects": self.projects,
            "expertise_areas": self.expertise_areas,
            "communication_preference": self.communication_preference,
            "timezone": self.timezone,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def get_memories_text(self) -> str:
        """Format memories for prompts."""
        if not self.memories:
            return ""
        lines = []
        for mem in self.memories:
            content = mem.get("content", str(mem))
            lines.append(f"- {content}")
        return "\n".join(lines)

    def get_context_text(self) -> str:
        """Get full context for prompts."""
        parts = []
        if self.name:
            parts.append(f"Name: {self.name}")
        if self.department:
            parts.append(f"Department: {self.department}")
        if self.role:
            parts.append(f"Role: {self.role}")
        if self.expertise_areas:
            parts.append(f"Expertise: {', '.join(self.expertise_areas)}")
        if self.communication_preference:
            parts.append(f"Prefers: {self.communication_preference} responses")
        if self.memories:
            parts.append(f"Notes:\n{self.get_memories_text()}")
        return "\n".join(parts)


# =============================================================================
# Custom Session Context Schema
# =============================================================================
@dataclass
class ProjectSessionContext:
    """Custom session context for project work."""

    session_id: str
    # Standard fields
    summary: Optional[str] = None
    goal: Optional[str] = None
    plan: List[str] = field(default_factory=list)
    progress: List[str] = field(default_factory=list)

    # Project-specific fields
    project_name: Optional[str] = None
    ticket_id: Optional[str] = None
    priority: Optional[str] = None  # "low", "medium", "high", "critical"
    blockers: List[str] = field(default_factory=list)
    decisions_made: List[Dict[str, str]] = field(default_factory=list)
    action_items: List[Dict[str, str]] = field(default_factory=list)

    # Metadata
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["ProjectSessionContext"]:
        if not isinstance(data, dict):
            return None
        try:
            valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            return cls(**filtered)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "summary": self.summary,
            "goal": self.goal,
            "plan": self.plan,
            "progress": self.progress,
            "project_name": self.project_name,
            "ticket_id": self.ticket_id,
            "priority": self.priority,
            "blockers": self.blockers,
            "decisions_made": self.decisions_made,
            "action_items": self.action_items,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def get_context_text(self) -> str:
        parts = []
        if self.project_name:
            parts.append(f"Project: {self.project_name}")
        if self.ticket_id:
            parts.append(f"Ticket: {self.ticket_id}")
        if self.priority:
            parts.append(f"Priority: {self.priority}")
        if self.summary:
            parts.append(f"Summary: {self.summary}")
        if self.goal:
            parts.append(f"Goal: {self.goal}")
        if self.blockers:
            parts.append(f"Blockers: {', '.join(self.blockers)}")
        if self.action_items:
            items = [f"- {a.get('item', a)}" for a in self.action_items]
            parts.append(f"Action Items:\n" + "\n".join(items))
        return "\n".join(parts)


# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# Create Agent with Custom Schemas
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        user_profile=UserProfileConfig(
            schema=EnterpriseUserProfile,  # Use custom schema!
            instructions=(
                "Extract: name, department, role, expertise areas, "
                "communication preference, projects they're working on"
            ),
        ),
        session_context=SessionContextConfig(
            schema=ProjectSessionContext,  # Use custom schema!
            enable_planning=True,
        ),
    ),
    markdown=True,
)


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    user_id = "hannah@enterprise.com"
    session_id = "project_alpha"

    # --- Establish rich context ---
    print("=" * 60)
    print("Establishing Enterprise Context")
    print("=" * 60)
    agent.print_response(
        "Hi! I'm Hannah from the Data Engineering team. I'm a Senior Engineer "
        "working on Project Alpha - our new data pipeline. I'm an expert in "
        "Apache Spark and Airflow. I prefer detailed technical discussions.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    # --- Check custom profile ---
    print("\n" + "=" * 60)
    print("Custom Profile Schema")
    print("=" * 60)
    profile = agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile:
        print(f"Type: {type(profile).__name__}")
        print(f"Department: {profile.department}")
        print(f"Role: {profile.role}")
        print(f"Expertise: {profile.expertise_areas}")
        print(f"Communication: {profile.communication_preference}")
        print(f"\nFull context:\n{profile.get_context_text()}")

    # --- Work on project ---
    print("\n" + "=" * 60)
    print("Working on Project")
    print("=" * 60)
    agent.print_response(
        "We're blocked on the Kafka integration - the topic permissions aren't "
        "set up yet. Can you help me draft a message to the platform team?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    # --- Check custom session context ---
    print("\n" + "=" * 60)
    print("Custom Session Schema")
    print("=" * 60)
    context = agent.learning.stores["session_context"].get(session_id=session_id)
    if context:
        print(f"Type: {type(context).__name__}")
        print(f"Project: {context.project_name}")
        print(f"Blockers: {context.blockers}")
        print(f"\nFull context:\n{context.get_context_text()}")
