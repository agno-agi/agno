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
    # =========================================================================
    # MEETING 1: Team Standup
    # =========================================================================
    print("=" * 70)
    print("MEETING 1: Team Standup")
    print("=" * 70)
    print("\nExpected: Create entities for team members and projects\n")

    standup = create_meeting_assistant("manager@company.com", "standup-2024-01-15")

    print("--- Meeting starts ---\n")
    standup.print_response(
        "Starting our Monday standup. Present: Alice (senior engineer), "
        "Bob (junior engineer), and myself. "
        "Please create entities for Alice and Bob if they don't exist.",
        stream=True,
    )

    print("\n--- Project updates ---\n")
    standup.print_response(
        "Alice: Project Atlas is on track for Q1 launch. Finished the auth module. "
        "Bob: Working on the onboarding flow for Atlas, blocked on API specs. "
        "Please track these updates on the appropriate entities and note that "
        "both Alice and Bob work on Project Atlas.",
        stream=True,
    )

    print("\n--- Action items ---\n")
    standup.print_response(
        "Action items from this standup: "
        "1. Alice to review Bob's PR by Wednesday "
        "2. Bob to sync with API team about specs "
        "3. I'll schedule Atlas demo for Friday. "
        "Please record these as events.",
        stream=True,
    )

    print("\n--- Session Context (meeting notes) ---")
    standup.get_learning_machine().session_context_store.print(
        session_id="standup-2024-01-15"
    )

    # =========================================================================
    # MEETING 2: 1:1 with Alice
    # =========================================================================
    print("\n" + "=" * 70)
    print("MEETING 2: 1:1 with Alice")
    print("=" * 70)
    print("\nExpected: Retrieve Alice entity, add career-related facts\n")

    one_on_one = create_meeting_assistant(
        "manager@company.com", "1on1-alice-2024-01-15"
    )

    print("--- 1:1 starts ---\n")
    one_on_one.print_response(
        "Starting 1:1 with Alice. First, what do we know about her from previous meetings?",
        stream=True,
    )

    print("\n--- Career discussion ---\n")
    one_on_one.print_response(
        "Alice shared she's interested in moving to a tech lead role. "
        "She wants to mentor Bob more actively. Her strength is system design. "
        "Please add these as facts to Alice's entity.",
        stream=True,
    )

    print("\n--- Session Context (1:1 notes) ---")
    one_on_one.get_learning_machine().session_context_store.print(
        session_id="1on1-alice-2024-01-15"
    )

    # =========================================================================
    # MEETING 3: Client Call with Acme Corp
    # =========================================================================
    print("\n" + "=" * 70)
    print("MEETING 3: Client Call with Acme Corp")
    print("=" * 70)
    print("\nExpected: Create company entity, track meeting decisions\n")

    client_call = create_meeting_assistant(
        "manager@company.com", "client-acme-2024-01-16"
    )

    print("--- Client call starts ---\n")
    client_call.print_response(
        "Client call with Acme Corp. Their CTO Sarah Chen is on the call. "
        "Please create entities for Acme Corp (company) and Sarah Chen (person), "
        "and note that Sarah is CTO at Acme.",
        stream=True,
    )

    print("\n--- Meeting discussion ---\n")
    client_call.print_response(
        "Acme wants to integrate Project Atlas into their platform. "
        "Timeline: Q2 launch. Budget approved for enterprise tier. "
        "Sarah will be our main point of contact. "
        "Track these details on the relevant entities.",
        stream=True,
    )

    print("\n--- Follow-ups ---\n")
    client_call.print_response(
        "Follow-up actions: "
        "1. Send Acme the technical specs by Friday "
        "2. Schedule deep-dive with their engineering team "
        "3. Alice to prepare integration guide. "
        "Record these as events.",
        stream=True,
    )

    # =========================================================================
    # Evidence Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("EVIDENCE SUMMARY")
    print("=" * 70)

    em = client_call.get_learning_machine().entity_memory_store

    print("\n[1] PEOPLE ENTITIES:")
    if em:
        for name in ["Alice", "Bob", "Sarah Chen"]:
            results = em.search(query=name, entity_type="person", limit=1)
            if results:
                print(f"\n    {name}:")
                entity = results[0]
                if hasattr(entity, "facts") and entity.facts:
                    for fact in entity.facts[:3]:
                        print(f"      - {fact.get('content', fact)}")
            else:
                print(f"\n    {name}: NOT FOUND")

    print("\n[2] PROJECT ENTITIES:")
    if em:
        results = em.search(query="Atlas", entity_type="project", limit=1)
        if results:
            print("\n    Project Atlas: FOUND")
            entity = results[0]
            if hasattr(entity, "facts") and entity.facts:
                for fact in entity.facts[:3]:
                    print(f"      - {fact.get('content', fact)}")

    print("\n[3] COMPANY ENTITIES:")
    if em:
        results = em.search(query="Acme", entity_type="company", limit=1)
        if results:
            print("\n    Acme Corp: FOUND")

    print("\n[4] SESSION CONTEXTS (meeting notes):")
    client_call.get_learning_machine().session_context_store.print(
        session_id="standup-2024-01-15"
    )
    client_call.get_learning_machine().session_context_store.print(
        session_id="client-acme-2024-01-16"
    )

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    print("""
Review the output above to verify:
- People, projects, and companies were created as entities
- Facts were added (roles, skills, project status)
- Events were logged (meetings, action items)
- Relationships link people to projects and companies
- Session context captured meeting notes and decisions
""")
