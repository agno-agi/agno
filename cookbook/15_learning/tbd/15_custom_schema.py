"""
Custom Schemas
===========================================
Customize the data structures used by learning stores.

## NEW: Field Metadata for LLM Visibility

When extending schemas, use field metadata to provide descriptions
that the LLM will see when deciding how to update fields:

    @dataclass
    class MyUserProfile(UserProfile):
        company: Optional[str] = field(
            default=None,
            metadata={"description": "Company or organization they work for"}
        )

The LLM sees these descriptions in the update_profile tool signature,
making it much more likely to correctly populate custom fields.

Use cases:
- Add fields specific to your domain
- Change how data is formatted
- Add validation logic
- Integrate with existing data models
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.learn.schemas import SessionContext, UserProfile
from agno.models.openai import OpenAIChat


# =============================================================================
# Custom User Profile Schema (with field metadata!)
# =============================================================================
@dataclass
class EnterpriseUserProfile(UserProfile):
    """Custom user profile with enterprise-specific fields.

    Note: We extend UserProfile to inherit base fields (user_id, name,
    preferred_name, memories) and add our own with descriptions.
    """

    # Enterprise-specific fields with descriptions for LLM
    department: Optional[str] = field(
        default=None,
        metadata={
            "description": "Department or team they work in (e.g., Engineering, Sales)"
        },
    )
    role: Optional[str] = field(
        default=None,
        metadata={
            "description": "Job title or role (e.g., Senior Engineer, Product Manager)"
        },
    )
    email: Optional[str] = field(
        default=None, metadata={"description": "Work email address"}
    )
    timezone: Optional[str] = field(
        default=None,
        metadata={
            "description": "User's timezone (e.g., America/New_York, Europe/London)"
        },
    )
    communication_preference: Optional[str] = field(
        default=None,
        metadata={
            "description": "How they prefer responses: brief, detailed, or technical"
        },
    )
    expertise_areas: Optional[str] = field(
        default=None, metadata={"description": "Areas of expertise, comma-separated"}
    )
    current_projects: Optional[str] = field(
        default=None, metadata={"description": "Projects they're currently working on"}
    )

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
            parts.append(f"Expertise: {self.expertise_areas}")
        if self.communication_preference:
            parts.append(f"Prefers: {self.communication_preference} responses")
        if self.current_projects:
            parts.append(f"Projects: {self.current_projects}")

        memories_text = self.get_memories_text()
        if memories_text:
            parts.append(f"Notes:\n{memories_text}")
        return "\n".join(parts)


# =============================================================================
# Custom Session Context Schema
# =============================================================================
@dataclass
class ProjectSessionContext(SessionContext):
    """Custom session context for project work.

    Extends SessionContext to add project-specific tracking.
    """

    # Project-specific fields
    project_name: Optional[str] = field(
        default=None, metadata={"description": "Name of the project being worked on"}
    )
    ticket_id: Optional[str] = field(
        default=None, metadata={"description": "Ticket or issue ID (e.g., PROJ-123)"}
    )
    priority: Optional[str] = field(
        default=None,
        metadata={"description": "Priority level: low, medium, high, or critical"},
    )
    blockers: Optional[str] = field(
        default=None, metadata={"description": "Current blockers or obstacles"}
    )

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
            parts.append(f"Blockers: {self.blockers}")
        if self.plan:
            plan_text = "\n".join(
                f"  {i + 1}. {step}" for i, step in enumerate(self.plan)
            )
            parts.append(f"Plan:\n{plan_text}")
        if self.progress:
            progress_text = "\n".join(f"  ✓ {step}" for step in self.progress)
            parts.append(f"Progress:\n{progress_text}")
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
            # The LLM will see all our custom fields with their descriptions
            # in the update_profile tool signature
            instructions=(
                "Extract enterprise context: department, role, expertise areas, "
                "communication preference, current projects. Use update_profile "
                "for structured data and add_memory for observations."
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

    # --- Show the custom fields the LLM will see ---
    print("=" * 60)
    print("Custom Profile Fields (LLM sees these in update_profile)")
    print("=" * 60)
    fields = EnterpriseUserProfile.get_updateable_fields()
    for name, info in fields.items():
        print(f"  {name}: {info['description']}")
    print()

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
    print("Custom Profile Schema Results")
    print("=" * 60)
    profile = agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile:
        print(f"Type: {type(profile).__name__}")
        print(f"Name: {profile.name}")
        print(f"Department: {profile.department}")
        print(f"Role: {profile.role}")
        print(f"Expertise: {profile.expertise_areas}")
        print(f"Communication: {profile.communication_preference}")
        print(f"Projects: {profile.current_projects}")
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
    print("Custom Session Schema Results")
    print("=" * 60)
    context = agent.learning.stores["session_context"].get(session_id=session_id)
    if context:
        print(f"Type: {type(context).__name__}")
        print(f"Project: {context.project_name}")
        print(f"Blockers: {context.blockers}")
        print(f"\nFull context:\n{context.get_context_text()}")
