"""
Pattern: On-Call Incident Response Bot
======================================
A DevOps scenario demonstrating cross-user knowledge sharing.

This cookbook demonstrates:
1. LearnedKnowledge AGENTIC mode - Bot saves incident patterns via tools
2. SessionContext - Current incident tracking with planning
3. Cross-user knowledge sharing - Solutions from one incident help others
4. Search and save learnings - Agent explicitly saves runbook patterns

Scenario:
- Engineer A reports a database connection issue, bot helps diagnose
- After resolution, engineer tells bot to save the pattern
- Engineer B (different person) has similar issue - bot finds prior solution

What makes this different from other cookbooks:
- support_agent.py: Stores work independently
- personal_assistant.py: Single user focus
- THIS: Multi-user knowledge sharing + incident tracking with save_learning
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Shared knowledge base for incident patterns
incident_kb = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="incident_runbooks",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


def create_oncall_bot(engineer_id: str, incident_id: str) -> Agent:
    """Create an incident response bot for an on-call engineer."""
    return Agent(
        model=OpenAIResponses(id="gpt-4o"),
        db=db,
        instructions="""\
You are an on-call incident response assistant. Your job:
1. Help diagnose and resolve production incidents
2. ALWAYS use search_learnings to find similar past incidents before suggesting solutions
3. Track incident progress (what's been tried, what worked)
4. When an incident is RESOLVED, use save_learning to record the pattern
   - Include: symptoms, root cause, resolution steps, prevention tips
   - This helps other engineers facing similar issues

Be concise and focus on actionable steps.""",
        learning=LearningMachine(
            knowledge=incident_kb,
            session_context=SessionContextConfig(
                enable_planning=True,  # Track incident resolution steps
            ),
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,  # Agent saves patterns via save_learning tool
                namespace="incidents:prod",
            ),
        ),
        user_id=engineer_id,
        session_id=incident_id,
        markdown=True,
    )


# ============================================================================
# Demo: Incident Response with Knowledge Sharing
# ============================================================================

if __name__ == "__main__":
    # Sarah encounters database connection storm
    print("\n" + "=" * 60)
    print("INCIDENT 1: Database Connection Storm (Sarah)")
    print("=" * 60 + "\n")

    sarah_initial_report = create_oncall_bot("sarah@company.com", "INC-001")
    sarah_initial_report.print_response(
        "I'm getting paged - our API is throwing 'too many connections' errors to Postgres. "
        "Response times are spiking. What should I check first?",
        stream=True,
    )
    sarah_initial_report.get_learning_machine().session_context_store.print(
        session_id="INC-001"
    )

    sarah_investigation = create_oncall_bot("sarah@company.com", "INC-001")
    sarah_investigation.print_response(
        "I checked pg_stat_activity - there are 500 connections! Our pool is set to 100. "
        "Most are in 'idle in transaction' state. What's causing this?",
        stream=True,
    )

    sarah_resolution = create_oncall_bot("sarah@company.com", "INC-001")
    sarah_resolution.print_response(
        "Found it! A new deployment had a missing connection.close() in a retry loop. "
        "Rolled back the deployment, connections dropping. Crisis averted! "
        "Root cause was unclosed connections in retry logic.",
        stream=True,
    )
    sarah_resolution.get_learning_machine().learned_knowledge_store.print(
        query="database connections"
    )

    # Marcus encounters similar issue
    print("\n" + "=" * 60)
    print("INCIDENT 2: Similar Database Issue (Marcus)")
    print("=" * 60 + "\n")

    marcus_similar_issue = create_oncall_bot("marcus@company.com", "INC-002")
    marcus_similar_issue.print_response(
        "Seeing Postgres connection exhaustion on the payments service. "
        "Pool is maxed out. What's the fastest way to diagnose?",
        stream=True,
    )

    # Verify cross-user knowledge sharing
    print("\n" + "=" * 60)
    print("VERIFICATION: Knowledge Sharing")
    print("=" * 60 + "\n")

    print("Learned knowledge (shared across engineers):")
    marcus_similar_issue.get_learning_machine().learned_knowledge_store.print(
        query="connection postgres"
    )

    print("\nSession contexts (separate per incident):")
    sarah_resolution.get_learning_machine().session_context_store.print(
        session_id="INC-001"
    )
    marcus_similar_issue.get_learning_machine().session_context_store.print(
        session_id="INC-002"
    )
