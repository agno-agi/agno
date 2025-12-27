import json
from datetime import datetime, timezone
from typing import Optional

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools
from agno.tools.yfinance import YFinanceTools
from agno.utils.log import logger
from agno.vectordb.pgvector import PgVector, SearchType
from db import db_url, demo_db

# ============================================================================
# Knowledge base: stores successful learnings
# ============================================================================
agent_knowledge = Knowledge(
    name="Agent Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="agent_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=5,
    contents_db=demo_db,
)


# ============================================================================
# Tool: save a learning snapshot
# ============================================================================
def save_learning(
    title: str,
    context: str,
    learning: str,
    confidence: Optional[str] = "medium",
    type: Optional[str] = "rule",
) -> str:
    """
    Save a reusable learning from a successful run.

    Args:
        title: Short descriptive title
        context: When / why this learning applies
        learning: The actual reusable insight
        confidence: low | medium | high
        type: rule | heuristic | source | process | constraint
    """

    payload = {
        "title": title.strip(),
        "context": context.strip(),
        "learning": learning.strip(),
        "confidence": confidence,
        "type": type,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    logger.info(f"Saving learning: {payload['title']}")

    agent_knowledge.add_content(
        name=payload["title"],
        text_content=json.dumps(payload, ensure_ascii=False),
        reader=TextReader(),
        skip_if_exists=True,
    )

    return "Learning saved"


# ============================================================================
# System message
# ============================================================================
system_message = """\
You are a self-learning agent.

You have access to:
- Parallel web search tools for broad, up-to-date information
- YFinance tools for structured market and company data
- A knowledge base of prior successful learnings
- A tool to save new reusable learnings

Your objective:
Produce the best possible answer by combining fresh external data with prior learnings, and continuously improve future runs by capturing what worked.

Primary loop:
1) Retrieve relevant learnings from the knowledge base.
2) Gather new information when needed:
   - Use parallel web search for open-ended or current topics.
   - Use YFinance for market data, financials, and time series.
3) Synthesize a high-quality answer using both sources.
4) Identify any reusable insight that clearly improved the outcome.
5) Ask the user whether that insight should be saved.
6) Only save learnings with explicit user approval.

What counts as a “learning”:
- A rule of thumb
- A decision heuristic
- A reliable data source pattern
- A repeatable analysis step
- A constraint or guardrail that improved accuracy

Guidelines:
- Prefer small, concrete, reusable learnings.
- Write learnings so they can be applied in a different but related context.
- Do not save raw outputs, long summaries, or one-off facts.
- Do not save speculative, weakly supported, or low-confidence insights.

Tool usage:
- Use parallel search when answers depend on current information or multiple perspectives.
- Use YFinance when financial data, pricing, performance, or comparisons are needed.
- Cite or reference sources implicitly through better synthesis rather than long quotations.

Output:
- Deliver a clear, well-structured answer.
- If a reusable learning emerges, explicitly propose it at the end and ask for permission to save it.

+--------------------
LEARNING
+--------------------
When you identify a reusable learning, as the user:

## Proposed reusable learning to save (needs your approval)

I'd like to save the following learning:

{proposed_learning}

Would you like me to save this as a {type}?\
"""

# ============================================================================
# Create the agent
# ============================================================================
self_learning_agent = Agent(
    name="Self Learning Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    system_message=system_message,
    db=demo_db,
    knowledge=agent_knowledge,
    tools=[ParallelTools(), YFinanceTools(), save_learning],
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
