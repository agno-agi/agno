"""
Custom Tool for Self-Learning - Write Your Own Tools
=====================================================
This example shows how to write custom tools for your agent.
A tool is just a Python function — the agent calls it when needed.

We'll build a self-learning agent that can save insights to a knowledge base.
The key concept: any function can become a tool.

Key concepts:
- Tools are Python functions with docstrings (the docstring tells the agent what the tool does)
- The agent decides when to call your tool based on the conversation
- Return a string to communicate results back to the agent

Example prompts to try:
- "What's a good P/E ratio for tech stocks? Save that insight."
- "Remember that NVDA's data center revenue is the key growth driver"
- "What learnings do we have saved?"
"""

import json
from datetime import datetime, timezone

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.reader.text_reader import TextReader
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.search import SearchType

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/agents.db")

# ============================================================================
# Knowledge Base for Learnings
# ============================================================================
learnings_kb = Knowledge(
    name="Agent Learnings",
    vector_db=ChromaDb(
        name="learnings",
        collection="learnings",
        path="tmp/chromadb",
        persistent_client=True,
        search_type=SearchType.hybrid,
        hybrid_rrf_k=60,
        embedder=GeminiEmbedder(id="gemini-embedding-001"),
    ),
    max_results=5,
    contents_db=agent_db,
)


# ============================================================================
# Custom Tool: Save Learning
# ============================================================================
def save_learning(title: str, learning: str) -> str:
    """
    Save a reusable insight to the knowledge base for future reference.

    Args:
        title: Short descriptive title (e.g., "Tech stock P/E benchmarks")
        learning: The insight to save — be specific and actionable

    Returns:
        Confirmation message
    """
    # Validate inputs
    if not title or not title.strip():
        return "Cannot save: title is required"
    if not learning or not learning.strip():
        return "Cannot save: learning content is required"

    # Build the payload
    payload = {
        "title": title.strip(),
        "learning": learning.strip(),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    # Save to knowledge base
    learnings_kb.add_content(
        name=payload["title"],
        text_content=json.dumps(payload, ensure_ascii=False),
        reader=TextReader(),
        skip_if_exists=True,
    )

    return f"Saved: '{title}'"


# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are a Finance Agent that learns and improves over time.

You have two special abilities:
1. Search your knowledge base for previously saved learnings
2. Save new insights using the save_learning tool

## Workflow

1. Check Knowledge First
   - Before answering, search for relevant prior learnings
   - Apply any relevant insights to your response

2. Gather Information
   - Use YFinance tools for market data
   - Combine with your knowledge base insights

3. Propose Learnings
   - After answering, consider: is there a reusable insight here?
   - If yes, propose it in this format:

---
**Proposed Learning**

Title: [concise title]
Learning: [the insight — specific and actionable]

Save this? (yes/no)
---

- Only call save_learning AFTER the user says "yes"
- If user says "no", acknowledge and move on

## What Makes a Good Learning

- Specific: "Tech P/E ratios typically range 20-35x" not "P/E varies"
- Actionable: Can be applied to future questions
- Reusable: Useful beyond this one conversation

Don't save: Raw data, one-off facts, or obvious information.\
"""

# ============================================================================
# Create the Agent
# ============================================================================
self_learning_agent = Agent(
    name="Self-Learning Agent",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[
        YFinanceTools(),
        save_learning,  # Our custom tool — just a Python function!
    ],
    knowledge=learnings_kb,
    search_knowledge=True,
    db=agent_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    # Ask a question that might produce a learning
    self_learning_agent.print_response(
        "What's a healthy P/E ratio for tech stocks?",
        stream=True,
    )

    # If the agent proposed a learning, approve it
    self_learning_agent.print_response(
        "yes",
        stream=True,
    )

    # Later, the agent can recall the learning
    self_learning_agent.print_response(
        "What learnings do we have saved?",
        stream=True,
    )

# ============================================================================
# More Examples
# ============================================================================
"""
Writing custom tools:

1. Define a function with type hints and a docstring
   def my_tool(param: str) -> str:
       '''Description of what this tool does.

       Args:
           param: What this parameter is for

       Returns:
           What the tool returns
       '''
       # Your logic here
       return "Result"

2. Add it to the agent's tools list
   agent = Agent(
       tools=[my_tool],
       ...
   )

The docstring is critical — it tells the agent:
- What the tool does
- What parameters it needs
- What it returns

The agent uses this to decide when and how to call your tool.
"""
