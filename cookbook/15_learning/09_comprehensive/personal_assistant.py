"""
Pattern: Personal Assistant with Multi-Channel Integration (ALL 5 Stores)
=========================================================================
An AI assistant managing daily communication across email, Slack, WhatsApp,
and meeting notes, learning user preferences and patterns over time.

This cookbook demonstrates:
1. UserProfile - User info, role, preferences
2. UserMemory - Communication patterns, work habits
3. SessionContext - Daily priorities, active threads
4. EntityMemory - Contacts, projects, relationships
5. LearnedKnowledge - Priority heuristics, decision patterns

Scenario:
Week-long journey showing assistant learning to prioritize, organize,
and proactively manage communication clutter across multiple channels.

Success metrics:
- Before learning: User manually triages 50+ messages daily
- After learning: Assistant surfaces 5-10 priority items, auto-handles rest
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Knowledge base for learned patterns
personal_kb = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="personal_assistant_kb",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


def create_personal_assistant(user_id: str, session_id: str) -> Agent:
    """Create personal assistant with all 5 learning stores."""
    return Agent(
        model=OpenAIResponses(id="gpt-4o"),
        db=db,
        instructions="""\
You are a personal assistant managing communication across email, Slack,
WhatsApp, and meeting notes.

YOUR RESPONSIBILITIES:
1. Prioritize messages based on learned patterns
2. Track important contacts, projects, and deadlines
3. Extract action items from meetings
4. Learn user preferences and communication patterns
5. Provide daily summaries and suggested next actions

ENTITY MANAGEMENT (use tools):
- search_entities: Find existing contacts/projects
- create_entity: Create person, project, or company entities
- add_fact: Add timeless info ("VP of Product", "Q1 deadline")
- add_event: Add timestamped events ("Meeting with Sarah on Jan 15")
- add_relationship: Link entities ("Alex works_with Sarah on LaunchProject")

PATTERN LEARNING (use tools):
- When you notice priority patterns, save them as learnings
- Example: "Emails from Sarah about LaunchProject are always urgent"

Be proactive, context-aware, and help reduce communication overwhelm.""",
        learning=LearningMachine(
            knowledge=personal_kb,
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            user_memory=UserMemoryConfig(
                mode=LearningMode.ALWAYS,
            ),
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"personal:{user_id}:life",
                enable_agent_tools=True,
            ),
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"personal:{user_id}:patterns",
            ),
        ),
        user_id=user_id,
        session_id=session_id,
        markdown=True,
    )


# ============================================================================
# Message Formatting Helpers
# ============================================================================


def format_email(sender: str, subject: str, preview: str) -> str:
    """Format email message."""
    return f"EMAIL from {sender}\nSubject: {subject}\n{preview}"


def format_slack(channel: str, sender: str, message: str) -> str:
    """Format Slack message."""
    return f"SLACK #{channel} - {sender}: {message}"


def format_whatsapp(sender: str, message: str) -> str:
    """Format WhatsApp message."""
    return f"WHATSAPP from {sender}: {message}"


def format_meeting(title: str, notes: str) -> str:
    """Format meeting notes."""
    return f"MEETING: {title}\n{notes}"


# ============================================================================
# Demo: 5-Day Personal Assistant Journey
# ============================================================================

if __name__ == "__main__":
    # Seed knowledge base with email management best practices from authoritative sources
    personal_kb.add_content(
        url="https://blog.superhuman.com/inbox-zero-method/", skip_if_exists=True
    )

    user_id = "alex@stripe.com"

    # Monday: Initial setup and message triage
    print("\n" + "=" * 60)
    print("MONDAY: Initial Setup & Message Triage")
    print("=" * 60 + "\n")

    intro_setup = create_personal_assistant(user_id, "week-jan-15")
    intro_setup.print_response(
        "Hi! I'm Alex Chen, product manager at Stripe working on payment APIs. "
        "I typically work 9-6 PT and prefer concise communication.",
        stream=True,
    )
    intro_setup.get_learning_machine().user_profile_store.print(user_id=user_id)

    sarah_urgent_email = create_personal_assistant(user_id, "week-jan-15")
    sarah_urgent_email.print_response(
        "Here's my first message this morning:\n\n"
        + format_email(
            "Sarah Chen <sarah@stripe.com>",
            "Product Launch - URGENT",
            "We need to discuss launch metrics before tomorrow's exec review.",
        ),
        stream=True,
    )

    monday_other_messages = create_personal_assistant(user_id, "week-jan-15")
    monday_other_messages.print_response(
        "I also have these messages:\n\n"
        + format_slack("product-team", "Bob", "Hey Alex, quick question about API docs")
        + "\n\n"
        + format_whatsapp("Mom", "Don't forget dinner tonight at 6!")
        + "\n\n"
        + "Help me prioritize all of today's messages.",
        stream=True,
    )
    monday_other_messages.get_learning_machine().session_context_store.print(
        session_id="week-jan-15"
    )

    # Tuesday: Pattern recognition
    print("\n" + "=" * 60)
    print("TUESDAY: Learning Priority Patterns")
    print("=" * 60 + "\n")

    tuesday_recap = create_personal_assistant(user_id, "week-jan-15")
    tuesday_recap.print_response(
        "Good morning! Yesterday I handled Sarah's urgent email first and it was the "
        "right call - the exec review went well.",
        stream=True,
    )

    tuesday_inbox = create_personal_assistant(user_id, "week-jan-15")
    tuesday_inbox.print_response(
        "Here's today's inbox:\n\n"
        + format_email(
            "Sarah Chen",
            "Launch Metrics Follow-up",
            "Great discussion yesterday...",
        )
        + "\n\n"
        + format_email(
            "Newsletter", "Weekly Product Digest", "Top 10 product trends..."
        )
        + "\n\n"
        + format_slack("product-team", "Sarah", "Can we sync on post-launch roadmap?"),
        stream=True,
    )

    tuesday_pattern_check = create_personal_assistant(user_id, "week-jan-15")
    tuesday_pattern_check.print_response(
        "What patterns do you see? How should I prioritize today?",
        stream=True,
    )
    tuesday_pattern_check.get_learning_machine().learned_knowledge_store.print(
        query="priority Sarah"
    )

    # Wednesday: Proactive assistance
    print("\n" + "=" * 60)
    print("WEDNESDAY: Proactive Prioritization")
    print("=" * 60 + "\n")

    wednesday_customer_issue = create_personal_assistant(user_id, "week-jan-15")
    wednesday_customer_issue.print_response(
        "Morning - I have an urgent message:\n\n"
        + format_email(
            "customer-success@acme.com",
            "URGENT: API Issue",
            "Customer reporting 500 errors on payment endpoint",
        ),
        stream=True,
    )

    wednesday_other_messages = create_personal_assistant(user_id, "week-jan-15")
    wednesday_other_messages.print_response(
        "Also received:\n\n"
        + format_slack("random", "Karen", "Anyone want coffee?")
        + "\n\n"
        + format_email(
            "Sarah Chen", "Post-launch retrospective", "Let's schedule for Friday"
        )
        + "\n\n"
        + "Use learned patterns to prioritize all messages today.",
        stream=True,
    )
    wednesday_other_messages.get_learning_machine().session_context_store.print(
        session_id="week-jan-15"
    )

    # Thursday: Cross-channel context tracking
    print("\n" + "=" * 60)
    print("THURSDAY: Cross-Channel Thread Tracking")
    print("=" * 60 + "\n")

    thursday_meeting = create_personal_assistant(user_id, "week-jan-15")
    thursday_meeting.print_response(
        format_meeting(
            "API Launch Retrospective",
            "Attendees: Sarah, Bob, Engineering team\n"
            "Discussed: Launch went well, 95% uptime\n"
            "Action items:\n"
            "- Alex: Draft Q2 roadmap by Friday\n"
            "- Bob: Update API docs with new examples\n"
            "- Sarah: Schedule customer feedback sessions",
        ),
        stream=True,
    )

    thursday_slack_followup = create_personal_assistant(user_id, "week-jan-15")
    thursday_slack_followup.print_response(
        "Later that day:\n\n"
        + format_slack("product-team", "Sarah", "Alex, how's the Q2 roadmap coming?")
        + "\n\n"
        + "What's the status on these action items?",
        stream=True,
    )
    thursday_slack_followup.get_learning_machine().session_context_store.print(
        session_id="week-jan-15"
    )

    # Friday: Week wrap-up
    print("\n" + "=" * 60)
    print("FRIDAY: Weekly Summary & Pattern Review")
    print("=" * 60 + "\n")

    friday_summary = create_personal_assistant(user_id, "week-jan-15")
    friday_summary.print_response(
        "It's Friday afternoon. Please:\n"
        "1. Summarize my week\n"
        "2. List any incomplete action\n"
        "3. Suggest prep for next week",
        stream=True,
    )
    friday_summary.get_learning_machine().learned_knowledge_store.print(
        query="priority pattern"
    )

    # Verify all 5 stores
    print("\n" + "=" * 60)
    print("VERIFICATION: All 5 Stores")
    print("=" * 60 + "\n")

    friday_summary.get_learning_machine().user_profile_store.print(user_id=user_id)
    friday_summary.get_learning_machine().session_context_store.print(
        session_id="week-jan-15"
    )
    friday_summary.get_learning_machine().learned_knowledge_store.print(
        query="priority"
    )
