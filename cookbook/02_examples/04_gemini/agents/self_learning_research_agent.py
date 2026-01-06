import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.models.google import Gemini
from agno.tools.parallel import ParallelTools
from agno.utils.log import logger
from agno.vectordb.pgvector import PgVector, SearchType
from db import db_url, gemini_agents_db

# =============================================================================
# Knowledge base for storing historical research snapshots
# =============================================================================
research_knowledge = Knowledge(
    name="Research Snapshots",
    vector_db=PgVector(
        db_url=db_url,
        table_name="research_snapshots",
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(id="gemini-embedding-001"),
    ),
    max_results=3,  # fetch a few candidates; agent selects latest by created_at
    contents_db=gemini_agents_db,
)


# =============================================================================
# Tool: Save a research snapshot (explicit user approval required)
# =============================================================================
def save_research_snapshot(
    name: str,
    question: str,
    report_summary: str,
    consensus_summary: str,
    claims: List[Dict[str, Any]],
    sources: List[Dict[str, str]],
    notes: Optional[str] = None,
) -> str:
    """Save a validated research snapshot to the knowledge base.

    Args:
        name: The name of the snapshot.
        question: The original question asked by the user.
        report_summary: A concise summary of this run (max 8 bullets or ~120 words).
        consensus_summary: 1–2 sentence consensus summary.
        claims: A list of claims supported by the evidence.
        sources: A list of sources used to support the claims.
        notes: Optional caveats, assumptions, or data-quality considerations.

    Returns:
        str: Status message.
    """

    if research_knowledge is None:
        return "Knowledge not available"

    payload = {
        "name": name.strip(),
        "question": question.strip(),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "report_summary": report_summary.strip(),
        "consensus_summary": consensus_summary.strip(),
        "claims": claims,
        "sources": sources,
        "notes": notes,
    }

    logger.info("Saving research snapshot")

    research_knowledge.add_content(
        name=payload["name"],
        text_content=json.dumps(payload, ensure_ascii=False),
        reader=TextReader(),
        skip_if_exists=False,  # snapshots are historical
    )

    return "Saved research snapshot to knowledge base"


# =============================================================================
# Instructions
# =============================================================================
instructions = """\
You are a self-learning research agent with access to web search and a knowledge base
containing prior research snapshots.

Your job:
- Answer the user's question using web search (via parallel_search).
- Summarize the current internet consensus as structured claims.
- Search your knowledge base for the most recent snapshot of a similar question.
- Compare the current claims to the prior snapshot and explain what changed and why.
- Ask the user if they want to save the new snapshot to the knowledge base.

You MUST follow this flow:
1) Use `parallel_search` tool to gather current information.
   - Issue MULTIPLE search queries in parallel (fan-out) and then aggregate results.
   - Cover at least:
     - Primary/official sources (docs, vendor pages, standards bodies)
     - Independent analysis (reputable industry blogs, benchmarks, research labs)
2) Use `search_knowledge` to retrieve up to 3 similar snapshots (if any).
3) From the retrieved snapshots, select the one with the newest `created_at` as "previous consensus".
4) Diff the current claims against the previous claims.
5) Present results using the format below.
6) Ask the user if they want to save the new snapshot to the knowledge base.

Consensus rules:
- A claim must be supported by at least two independent sources, unless it is a primary/official source.
- If sources disagree, mark the claim as disputed and lower confidence.

Response format (must follow exactly):

## Quick Answer
(2-4 sentences)

## Research Summary
(Structured sections with bullets)

## Current Consensus (Claims)
Provide 4-10 claims. Each claim must include:
- claim_id: stable id (generate a short slug)
- claim: short statement
- confidence: Low | Medium | High
- source_urls: 1-3 URLs

## What Changed Since Last Time
- If a prior snapshot exists:
  - New or strengthened claims
  - Weakened or disputed claims
  - Removed claims
  - For each change, briefly explain why and cite sources
- If no prior snapshot exists:
  - Say: “No prior snapshot found. This is the first recorded consensus.”

## Sources
- Deduplicate URLs
- Prefer canonical URLs
- Max 12 sources
(Clickable URLs)

After the response, add:

## Save Snapshot?
"Want me to save this snapshot to the knowledge base for future comparisons?"

Rules:
- Clearly separate facts from interpretation.
- Note uncertainty or outdated information explicitly.
- Ask the user if they want to save the new snapshot to the knowledge base and then call the `save_research_snapshot` tool if they say yes.
"""


# =============================================================================
# Create the agent
# =============================================================================
self_learning_research_agent = Agent(
    name="Self Learning Research Agent",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    db=gemini_agents_db,
    knowledge=research_knowledge,
    tools=[ParallelTools(), save_research_snapshot],
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


if __name__ == "__main__":
    self_learning_research_agent.print_response(
        "What is the current consensus on using AI agents in enterprise production systems?",
        stream=True,
    )
