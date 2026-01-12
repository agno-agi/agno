"""
Pattern: Meeting Assistant with Entity & Action Tracking
========================================================
An assistant that tracks people, projects, and action items across meetings.

This cookbook demonstrates:
1. EntityMemory AGENTIC mode - Track people, companies, projects
2. SessionContext with planning - Track meeting agenda, decisions, action items
3. Cross-meeting entity continuity - Same person/project across multiple meetings
4. Relationship tracking - Who works on what, who reports to whom

Scenario:
- Meeting 1: Team standup - track attendees, project updates, blockers
- Meeting 2: 1:1 with team member - track career goals, action items
- Meeting 3: Client call - track client entity, meeting notes, follow-ups

Key features demonstrated:
- Entity creation for people, projects, companies
- Event logging on entities (meetings, updates, decisions)
- Relationship tracking (works_on, reports_to, owns)
- Session context for meeting notes and action items
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    EntityMemoryConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
)
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)


def create_meeting_assistant(user_id: str, meeting_id: str) -> Agent:
    """Create a meeting assistant for tracking entities and action items."""
    return Agent(
        model=OpenAIResponses(id="gpt-4o"),
        db=db,
        instructions="""\
You are a meeting assistant that tracks people, projects, and action items.

YOUR RESPONSIBILITIES:
1. Track entities mentioned in meetings (people, projects, companies)
2. Record meeting events, decisions, and action items
3. Link entities with relationships (works_on, reports_to, owns)
4. Recall relevant context from previous meetings

ENTITY MANAGEMENT (use these tools):
- search_entities: Find existing people/projects before creating new ones
- create_entity: Create new entities (entity_id format: lowercase_with_underscores)
- add_fact: Add timeless info ("Senior Engineer", "Q1 priority project")
- add_event: Add meeting events with dates ("Discussed in standup", "Assigned task X")
- add_relationship: Link entities ("alice works_on project_atlas")

Entity types: "person", "project", "company"

WORKFLOW:
1. When someone is mentioned, search first, then create if not found
2. Add relevant facts and events to entities
3. Track relationships between people and projects
4. Summarize action items at the end of meetings

Be thorough - every person, project, and decision should be tracked.""",
        learning=LearningMachine(
            session_context=SessionContextConfig(
                enable_planning=True,  # Track meeting agenda and action items
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                namespace="meetings:team",
                enable_agent_tools=True,
            ),
        ),
        user_id=user_id,
        session_id=meeting_id,
        markdown=True,
    )


# ============================================================================
# Demo: Meeting Assistant Scenario
# ============================================================================

if __name__ == "__main__":
    # Team standup meeting
    print("\n" + "=" * 60)
    print("MEETING 1: Team Standup")
    print("=" * 60 + "\n")

    standup_intro = create_meeting_assistant(
        "manager@company.com", "standup-2024-01-15"
    )
    standup_intro.print_response(
        "Starting our Monday standup. Present: Alice (senior engineer), "
        "Bob (junior engineer), and myself.",
        stream=True,
    )

    standup_updates = create_meeting_assistant(
        "manager@company.com", "standup-2024-01-15"
    )
    standup_updates.print_response(
        "Alice: Project Atlas is on track for Q1 launch. Finished the auth module. "
        "Bob: Working on the onboarding flow for Atlas, blocked on API specs. "
        "Both Alice and Bob are working on Project Atlas.",
        stream=True,
    )

    standup_action_items = create_meeting_assistant(
        "manager@company.com", "standup-2024-01-15"
    )
    standup_action_items.print_response(
        "Action items from this standup: "
        "1. Alice to review Bob's PR by Wednesday "
        "2. Bob to sync with API team about specs "
        "3. I'll schedule Atlas demo for Friday.",
        stream=True,
    )
    standup_action_items.get_learning_machine().session_context_store.print(
        session_id="standup-2024-01-15"
    )

    # 1:1 meeting with Alice
    print("\n" + "=" * 60)
    print("MEETING 2: 1:1 with Alice")
    print("=" * 60 + "\n")

    one_on_one_context = create_meeting_assistant(
        "manager@company.com", "1on1-alice-2024-01-15"
    )
    one_on_one_context.print_response(
        "Starting 1:1 with Alice. What do we know about her from previous meetings?",
        stream=True,
    )

    one_on_one_discussion = create_meeting_assistant(
        "manager@company.com", "1on1-alice-2024-01-15"
    )
    one_on_one_discussion.print_response(
        "Alice shared she's interested in moving to a tech lead role. "
        "She wants to mentor Bob more actively. Her strength is system design.",
        stream=True,
    )
    one_on_one_discussion.get_learning_machine().session_context_store.print(
        session_id="1on1-alice-2024-01-15"
    )

    # Client call with Acme Corp
    print("\n" + "=" * 60)
    print("MEETING 3: Client Call with Acme Corp")
    print("=" * 60 + "\n")

    client_call_intro = create_meeting_assistant(
        "manager@company.com", "client-acme-2024-01-16"
    )
    client_call_intro.print_response(
        "Client call with Acme Corp. Their CTO Sarah Chen is on the call. "
        "Sarah is CTO at Acme.",
        stream=True,
    )

    client_call_discussion = create_meeting_assistant(
        "manager@company.com", "client-acme-2024-01-16"
    )
    client_call_discussion.print_response(
        "Acme wants to integrate Project Atlas into their platform. "
        "Timeline: Q2 launch. Budget approved for enterprise tier. "
        "Sarah will be our main point of contact.",
        stream=True,
    )

    client_call_followups = create_meeting_assistant(
        "manager@company.com", "client-acme-2024-01-16"
    )
    client_call_followups.print_response(
        "Follow-up actions: "
        "1. Send Acme the technical specs by Friday "
        "2. Schedule deep-dive with their engineering team "
        "3. Alice to prepare integration guide.",
        stream=True,
    )

    # Verify entities were created
    print("\n" + "=" * 60)
    print("VERIFICATION: Entity Tracking")
    print("=" * 60 + "\n")

    em = client_call_followups.get_learning_machine().entity_memory_store

    print("People entities:")
    if em:
        for name in ["Alice", "Bob", "Sarah Chen"]:
            results = em.search(query=name, entity_type="person", limit=1)
            if results:
                entity = results[0]
                print(
                    f"  {name}: {len(entity.facts) if hasattr(entity, 'facts') else 0} facts"
                )
            else:
                print(f"  {name}: NOT FOUND")

    print("\nProject entities:")
    if em:
        results = em.search(query="Atlas", entity_type="project", limit=1)
        if results:
            print("  Project Atlas: FOUND")

    print("\nCompany entities:")
    if em:
        results = em.search(query="Acme", entity_type="company", limit=1)
        if results:
            print("  Acme Corp: FOUND")

    print("\nSession contexts:")
    client_call_followups.get_learning_machine().session_context_store.print(
        session_id="standup-2024-01-15"
    )
    client_call_followups.get_learning_machine().session_context_store.print(
        session_id="client-acme-2024-01-16"
    )
