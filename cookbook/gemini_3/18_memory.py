"""
18. Memory + Learning
=====================
The agent learns from interactions and improves over time.
Interaction 1,000 should be better than interaction 1.

This builds on step 17 by adding:
- LearningMachine: Captures insights and user preferences
- LearnedKnowledge (AGENTIC mode): Agent decides what to save and retrieve
- Agentic memory: Builds user profiles over time
- ReasoningTools: The think tool for structured reasoning

Run:
    python cookbook/gemini_3/18_memory.py

Example:
    Session 1: User teaches a preference
    Session 2: Agent applies it without being reminded
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.google import Gemini
from agno.tools.reasoning import ReasoningTools
from agno.vectordb.chroma import ChromaDb, SearchType

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
db = SqliteDb(db_file=str(WORKSPACE / "gemini_agents.db"))

# ---------------------------------------------------------------------------
# Knowledge: Static docs (teaching materials)
# ---------------------------------------------------------------------------
docs_knowledge = Knowledge(
    name="Tutor Knowledge",
    vector_db=ChromaDb(
        collection="tutor-materials",
        path=str(WORKSPACE / "chromadb"),
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(),
    ),
    contents_db=db,
)

# ---------------------------------------------------------------------------
# Knowledge: Dynamic learnings (agent learns over time)
# ---------------------------------------------------------------------------
learned_knowledge = Knowledge(
    vector_db=ChromaDb(
        collection="tutor-learnings",
        path=str(WORKSPACE / "chromadb"),
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(),
    ),
    contents_db=db,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
tutor_agent = Agent(
    name="Personal Tutor",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a personal language tutor that adapts to each student.

## Workflow

1. Check your learnings and memory for this user's preferences and level
2. Tailor your response to their skill level and learning style
3. Save any new insights about the student for future sessions

## Rules

- Adapt difficulty to the student's level
- Follow the student's preferred learning style
- Track progress and build on previous lessons
- Provide corrections gently with explanations\
""",
    tools=[ReasoningTools()],
    knowledge=docs_knowledge,
    search_knowledge=True,
    learning=LearningMachine(
        knowledge=learned_knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
    enable_agentic_memory=True,
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = "student@example.com"

    # Session 1: User teaches the agent their preferences
    print("\n" + "=" * 60)
    print("SESSION 1: Teaching the agent your preferences")
    print("=" * 60 + "\n")

    tutor_agent.print_response(
        "I'm learning Spanish. I'm at an intermediate level and I prefer "
        "learning through conversations rather than grammar drills. "
        "Can you help me practice ordering food at a restaurant?",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )

    # Show what the agent learned
    if tutor_agent.learning_machine:
        print("\n--- Learned Knowledge ---")
        tutor_agent.learning_machine.learned_knowledge_store.print(
            query="student preferences"
        )

    # Session 2: New task -- agent should apply learned preferences
    print("\n" + "=" * 60)
    print("SESSION 2: New task -- agent should apply learned preferences")
    print("=" * 60 + "\n")

    tutor_agent.print_response(
        "Can you help me practice asking for directions?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
