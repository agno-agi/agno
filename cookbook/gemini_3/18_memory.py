"""
Memory + Learning - Agent That Improves Over Time
===================================================
The agent learns from interactions so response 1,000 is better than response 1.

Key concepts:
- LearningMachine: Manages knowledge the agent discovers during conversations
- LearningMode.AGENTIC: Agent decides when to save insights (vs ALWAYS or NEVER)
- enable_agentic_memory: Builds user profiles from conversation patterns
- ReasoningTools: Lets the agent "think" before responding (separate from model thinking)
- Two knowledge stores: Static (docs) + dynamic (learned), searched together

Example prompts to try:
- Session 1: "I'm learning Spanish. I prefer conversations over grammar drills."
- Session 2: "Help me practice asking for directions." (agent remembers preferences)
"""

from pathlib import Path

from agno.agent import Agent
from agno.knowledge import Knowledge
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.google import Gemini
from agno.tools.reasoning import ReasoningTools
from agno.vectordb.chroma import ChromaDb, SearchType
from db import gemini_agents_db

WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

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
    contents_db=gemini_agents_db,
)

# ---------------------------------------------------------------------------
# Knowledge: Dynamic learnings (agent discovers over time)
# ---------------------------------------------------------------------------
learned_knowledge = Knowledge(
    vector_db=ChromaDb(
        collection="tutor-learnings",
        path=str(WORKSPACE / "chromadb"),
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(),
    ),
    contents_db=gemini_agents_db,
)

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
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
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
tutor_agent = Agent(
    name="Personal Tutor",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    # ReasoningTools gives the agent a "think" tool for structured reasoning
    tools=[ReasoningTools()],
    knowledge=docs_knowledge,
    search_knowledge=True,
    learning=LearningMachine(
        knowledge=learned_knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            # AGENTIC: Agent decides what to save (vs ALWAYS saving everything)
            mode=LearningMode.AGENTIC,
        ),
    ),
    # Builds user profiles from conversation patterns
    enable_agentic_memory=True,
    db=gemini_agents_db,
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

    # Session 2: New task, agent should apply learned preferences
    print("\n" + "=" * 60)
    print("SESSION 2: New task, agent applies learned preferences")
    print("=" * 60 + "\n")

    tutor_agent.print_response(
        "Can you help me practice asking for directions?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Learning modes:

1. LearningMode.AGENTIC (this example)
   Agent decides what to save. Best for production.
   The agent saves genuinely useful insights, not noise.

2. LearningMode.ALWAYS
   Save everything. Useful for debugging and development.
   Can get noisy in production.

3. LearningMode.NEVER
   Disable learning. Useful for stateless agents.

The learning architecture:
- Static knowledge: Documents you load (recipes, manuals, docs)
- Dynamic knowledge: Insights the agent discovers during conversations
- Memory: User profiles built from interaction patterns
- All three are searched together when the agent needs context.
"""
