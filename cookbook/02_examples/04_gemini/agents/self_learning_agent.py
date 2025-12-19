"""
Self-Learning Agent
====================
GPU Poor Continuous Learning: System-level learning without fine-tuning.

The loop:
1. Search knowledge base for relevant learnings
2. Gather fresh information (search, APIs)
3. Synthesize answer using both
4. Identify reusable insight
5. Save with user approval

Built with Agno + Gemini 3 Flash
"""

import json
from datetime import datetime, timezone

from agno.agent import Agent
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.models.google import Gemini
from agno.tools.parallel import ParallelTools
from agno.tools.yfinance import YFinanceTools
from agno.utils.log import logger
from agno.vectordb.pgvector import PgVector, SearchType
from db import db_url, gemini_agents_db

# ============================================================================
# Knowledge Base: stores successful learnings
# ============================================================================
agent_knowledge = Knowledge(
    name="Agent Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="agent_learnings",
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(id="gemini-embedding-001"),
    ),
    max_results=5,
    contents_db=gemini_agents_db,
)


# ============================================================================
# Tool: Save Learning
# ============================================================================
def save_learning(
    title: str,
    context: str,
    learning: str,
    confidence: str = "medium",
    type: str = "rule",
) -> str:
    """
    Save a reusable learning from a successful run.

    Args:
        title: Short descriptive title (e.g., "API rate limit handling")
        context: When/why this learning applies (e.g., "When calling external APIs...")
        learning: The actual reusable insight (be specific and actionable)
        confidence: low | medium | high
        type: rule | heuristic | source | process | constraint

    Returns:
        Status message indicating what happened
    """
    # Validate inputs
    if not title or not title.strip():
        return "Cannot save: title is required"
    if not learning or not learning.strip():
        return "Cannot save: learning content is required"
    if len(learning.strip()) < 20:
        return "Cannot save: learning is too short to be useful. Be more specific."
    if confidence not in ("low", "medium", "high"):
        return f"Cannot save: confidence must be low|medium|high, got '{confidence}'"
    if type not in ("rule", "heuristic", "source", "process", "constraint"):
        return f"Cannot save: type must be rule|heuristic|source|process|constraint, got '{type}'"

    # Build the learning payload
    payload = {
        "title": title.strip(),
        "context": context.strip() if context else "",
        "learning": learning.strip(),
        "confidence": confidence,
        "type": type,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # Save to knowledge base
    try:
        agent_knowledge.add_content(
            name=payload["title"],
            text_content=json.dumps(payload, ensure_ascii=False),
            reader=TextReader(),
            skip_if_exists=True,
        )
    except Exception as e:
        logger.error(f"[Learning] Failed to save: {e}")
        return f"Failed to save learning: {e}"

    logger.info(f"[Learning] Saved: {payload['title']}")
    return f"Learning saved: '{payload['title']}'"


# ============================================================================
# Instructions
# ============================================================================
instructions = """\
You are a Self-Learning Agent that improves over time by capturing and reusing successful patterns.

You build institutional memory: successful insights get saved to a knowledge base and retrieved on future runs. The model stays fixed, but the system gets smarter.

## Tools

| Tool | Use For |
|------|---------|
| search_knowledge | Retrieve relevant prior learnings |
| parallel_search | Web search, current information |
| yfinance | Market data, financials, company info |
| save_learning | Store a reusable insight (requires user approval) |

## Workflow

For every request:

1. SEARCH KNOWLEDGE FIRST — Always call `search_knowledge` before anything else. Extract key concepts from the user's query and search for relevant learnings. If nothing relevant is found, proceed without prior context.
2. RESEARCH — Use `parallel_search` or `yfinance` to gather fresh information as needed.
3. SYNTHESIZE — Combine prior learnings (if any) with new information. When applying a prior learning, reference it naturally: "Based on a previous pattern..." or "A prior learning suggests..."
4. REFLECT — After answering, consider: did this task reveal a reusable insight? Most queries will not produce a learning. Only flag genuine discoveries.
5. PROPOSE (if applicable) — If you identified something worth saving, propose it at the end of your response. Never call save_learning without explicit user approval.

## What Makes a Good Learning

A learning is worth saving if it is:
- Specific: "When comparing ETFs, check expense ratio AND tracking error" not "Look at ETF metrics"
- Actionable: Can be directly applied in future similar queries
- Generalizable: Useful beyond this specific question

Do not save: raw facts, one-off answers, summaries, speculation, or anything unlikely to recur.

Most tasks will not produce a learning. That's expected.

## Proposing a Learning

When you have a genuine insight worth saving, end your response with:

---
Proposed Learning

Title: [concise title]
Type: rule | heuristic | source | process | constraint
Context: [when to apply this]
Learning: [the insight — specific and actionable]

Save this? (yes/no)
---

If the user declines, acknowledge and move on. Do not re-propose the same learning.
"""


# ============================================================================
# Create the Agent
# ============================================================================
self_learning_agent = Agent(
    name="Self-Learning Agent",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    db=gemini_agents_db,
    knowledge=agent_knowledge,
    tools=[
        ParallelTools(),
        YFinanceTools(),
        save_learning,
    ],
    # Enable the agent to remember user information and preferences
    enable_agentic_memory=True,
    # Enable the agent to search the knowledge base (i.e previous research snapshots)
    search_knowledge=True,
    # Add the current date and time to the context
    add_datetime_to_context=True,
    # Add the history of the agent's runs to the context
    add_history_to_context=True,
    # Number of historical runs to include in the context
    num_history_runs=5,
    # Give the agent a tool to read chat history beyond the last 5 messages
    read_chat_history=True,
    markdown=True,
)


# ============================================================================
# CLI
# ============================================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        self_learning_agent.print_response(query, stream=True)
    else:
        print("=" * 60)
        print("🧠 Self-Learning Agent")
        print("   GPU Poor Continuous Learning with Gemini 3 Flash")
        print("=" * 60)
        print("\nType 'quit' to exit.\n")

        while True:
            try:
                user_input = input("You: ").strip()
                if user_input.lower() in ("quit", "exit", "q"):
                    print("\n👋 Goodbye!")
                    break
                if not user_input:
                    continue

                print()
                self_learning_agent.print_response(user_input, stream=True)
                print()

            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
