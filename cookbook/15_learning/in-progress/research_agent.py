"""
Pattern: Research Agent
=======================
Research assistant with entity tracking and knowledge accumulation.

This agent demonstrates:
- Entity memory for tracking research subjects
- Learned knowledge for capturing insights
- User profile for research preferences
- Session context for multi-step research projects

Run standalone:
    python cookbook/15_learning/patterns/research_agent.py

Or via AgentOS:
    python cookbook/15_learning/run.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearningMachine,
    UserProfileConfig,
    SessionContextConfig,
    LearnedKnowledgeConfig,
    EntityMemoryConfig,
    LearningMode,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# Knowledge base for research insights
research_knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="research_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Research Agent
# ============================================================================
research_agent = Agent(
    name="Research Agent",
    agent_id="research-agent",
    model=model,
    db=db,
    instructions="""\
You are a research assistant that helps users explore topics deeply.

Your capabilities:
1. **Entity Tracking**: Track companies, people, papers, technologies as entities
2. **Knowledge Building**: Accumulate insights across research sessions
3. **User Memory**: Remember research interests and methodology preferences
4. **Session Planning**: Plan and track multi-step research projects

Research Approach:
- Break down complex topics into researchable questions
- Track sources and confidence levels
- Connect findings across entities
- Identify patterns and contradictions

When researching:
- Create entities for key subjects
- Add facts with source attribution
- Track events and timelines
- Map relationships between entities

When you discover valuable insights:
- Save them as learnings for future reference
- Tag them with relevant categories
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=research_knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,  # Research benefits from planning
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="research",
            enable_agent_tools=True,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="research",
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Research Project
# ============================================================================
def demo_research():
    """Demonstrate a research project."""
    print("=" * 60)
    print("Demo: Research Agent")
    print("=" * 60)

    user = "researcher@example.com"
    session = "research_project_001"

    # Start research
    print("\n--- Start research project ---\n")
    research_agent.print_response(
        "I want to research the current state of AI agent frameworks. "
        "Help me understand the major players, their approaches, and trade-offs.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Track findings
    print("\n--- Track research findings ---\n")
    research_agent.print_response(
        "Let me share what I've found so far: "
        "LangChain is the most popular, uses chains and tools abstraction. "
        "AutoGPT pioneered autonomous agents but has reliability issues. "
        "CrewAI focuses on multi-agent collaboration. "
        "Agno emphasizes production-ready features and learning. "
        "Please track all these as entities.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Save insight
    print("\n--- Save research insight ---\n")
    research_agent.print_response(
        "I've noticed a pattern: the frameworks that focus on reliability "
        "(like Agno) sacrifice some flexibility, while those that focus on "
        "flexibility (like LangChain) often have reliability issues in production. "
        "This seems like a fundamental trade-off. Save this insight.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Continuing Research
# ============================================================================
def demo_continue():
    """Show continuing research with accumulated knowledge."""
    print("\n" + "=" * 60)
    print("Demo: Continuing Research")
    print("=" * 60)

    user = "researcher@example.com"
    session = "research_project_002"

    print("\n--- Continue research ---\n")
    research_agent.print_response(
        "Let's continue my AI frameworks research. Based on what we've "
        "learned, which framework would be best for a production chatbot?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Cross-Entity Analysis
# ============================================================================
def demo_cross_entity():
    """Show analysis across multiple entities."""
    print("\n" + "=" * 60)
    print("Demo: Cross-Entity Analysis")
    print("=" * 60)

    user = "analyst@example.com"
    session = "analysis_session"

    # Track multiple entities
    print("\n--- Track multiple entities ---\n")
    research_agent.print_response(
        "Track these AI companies for my competitive analysis: "
        "OpenAI - founded 2015, valued at $80B, known for GPT models "
        "Anthropic - founded 2021, valued at $15B, known for Claude, safety focus "
        "Google DeepMind - merged 2023, parent is Alphabet, known for Gemini "
        "Please create entities with relationships to their key products.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Cross-entity analysis
    print("\n--- Analyze across entities ---\n")
    research_agent.print_response(
        "Compare the AI companies I'm tracking. What are their different "
        "strategic approaches and how do they compete?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_research()
    demo_continue()
    demo_cross_entity()

    print("\n" + "=" * 60)
    print("✅ Research Agent for deep topic exploration")
    print("   - Tracks research subjects as entities")
    print("   - Accumulates insights as learnings")
    print("   - Plans and tracks research projects")
    print("=" * 60)
