"""
Level 3: Agent with memory and learning
====================================
The agent now learns from interactions and improves over time.
Interaction 1,000 should be better than interaction 1.

This builds on Level 2 by adding:
- LearningMachine: Captures insights and user preferences
- LearnedKnowledge (AGENTIC mode): Agent decides what to save and retrieve
- Agentic memory: Builds user profiles over time
- ReasoningTools: The think tool for structured reasoning

Run standalone:
    python cookbook/levels_of_agentic_software/level_3_memory_learning.py

Run via Agent OS:
    python cookbook/levels_of_agentic_software/run.py
    Then visit https://os.agno.com and select "L3 Coding Agent"

Example prompt:
    "Write a data pipeline using functional programming style"
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses
from agno.tools.coding import CodingTools
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
db = SqliteDb(db_file=str(WORKSPACE / "agents.db"))

# ---------------------------------------------------------------------------
# Knowledge: Static docs (project conventions)
# ---------------------------------------------------------------------------
docs_knowledge = Knowledge(
    vector_db=ChromaDb(
        collection="coding-standards",
        path=str(WORKSPACE / "chromadb"),
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=db,
)

# ---------------------------------------------------------------------------
# Knowledge: Dynamic learnings (agent learns over time)
# ---------------------------------------------------------------------------
learned_knowledge = Knowledge(
    vector_db=ChromaDb(
        collection="coding-learnings",
        path=str(WORKSPACE / "chromadb"),
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=db,
)

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a coding agent that learns and improves over time.

## Workflow

1. Search your knowledge and learnings for relevant context
2. Check if the user has preferences you should follow
3. Write code that follows conventions and user preferences
4. Save the code to a file and run it to verify
5. Save any valuable insights or patterns for future use

## Rules

- Always search knowledge and learnings before writing code
- Apply user preferences from memory when writing code
- Save useful coding patterns and insights as learnings
- Follow project conventions from the knowledge base
- No emojis\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
l3_coding_agent = Agent(
    name="L3 Coding Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=instructions,
    tools=[
        CodingTools(base_dir=WORKSPACE, all=True),
        ReasoningTools(),
    ],
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
    user_id = "dev@example.com"

    # Session 1: User teaches a preference, agent learns it
    print("\n" + "=" * 60)
    print("SESSION 1: Teaching the agent your preferences")
    print("=" * 60 + "\n")

    l3_coding_agent.print_response(
        "I strongly prefer functional programming style -- no classes, "
        "use pure functions, immutable data structures, and composition. "
        "Remember this preference for all future coding tasks. "
        "Now write a data pipeline that reads a list of numbers, filters evens, "
        "doubles them, and computes the sum. Save it to pipeline.py and run it.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )

    # Show what the agent learned
    if l3_coding_agent.learning_machine:
        print("\n--- Learned Knowledge ---")
        l3_coding_agent.learning_machine.learned_knowledge_store.print(
            query="coding preferences"
        )

    # Session 2: New task -- agent should apply learned preferences
    print("\n" + "=" * 60)
    print("SESSION 2: New task -- agent should apply learned preferences")
    print("=" * 60 + "\n")

    l3_coding_agent.print_response(
        "Write a log parser that reads a log file, extracts error lines, "
        "groups them by error category, and returns a count per category. "
        "Save it to log_parser.py and run it with sample data.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
