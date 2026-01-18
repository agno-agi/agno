import json
from datetime import datetime, timezone
from typing import Optional

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools
from agno.utils.log import logger
from agno.vectordb.pgvector import PgVector, SearchType
from db import db_url, demo_db

# =============================================================================
# Knowledge base for storing historical research snapshots
# =============================================================================
research_snapshots = Knowledge(
    name="Research Snapshots",
    vector_db=PgVector(
        db_url=db_url,
        table_name="research_snapshots",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=3,  # fetch a few candidates; agent selects latest by created_at
    contents_db=demo_db,
)


# =============================================================================
# Tool: Save a research snapshot (explicit user approval required)
# =============================================================================
def save_research_snapshot(
    name: str,
    question: str,
    report_summary: str,
    consensus_summary: str,
    claims: str,
    sources: str,
    notes: Optional[str] = None,
) -> str:
    """Save a validated research snapshot to the knowledge base.
    This snapshot records the current consensus at a point in time so future runs can compare what changed and why.

    Args:
        name:
            Short, human-readable snapshot name.
            Example: "AI agents in enterprise production (Dec 2025)"

        question:
            The original user question exactly as asked.

        report_summary:
            A concise summary of this run.
            - Max 8 bullet points OR ~120 words
            - Plain text only (no markdown)

        consensus_summary:
            A 1-2 sentence summary describing the overall consensus.

        claims:
            A JSON STRING representing a LIST of claim objects.

            Required JSON schema:
            [
              {
                "claim_id": "stable.short.slug",
                "claim": "Short factual statement",
                "confidence": "Low | Medium | High",
                "source_urls": ["https://example.com", "..."]
              }
            ]

            Rules:
            - Must be valid JSON
            - Must be a list, not a dict
            - Each claim must include all required fields
            - source_urls must be a list of 1–3 URLs

        sources:
            A JSON STRING representing a LIST of source objects.

            Required JSON schema:
            [
              {
                "title": "Source title",
                "url": "https://example.com"
              }
            ]

            Rules:
            - Must be valid JSON
            - Deduplicate URLs
            - Prefer canonical URLs (no tracking params)

        notes:
            Optional plain-text notes for caveats, uncertainty, or data quality issues.
            Use null if not needed.

    Returns:
        A short status message indicating whether the snapshot was saved successfully.
    """

    if research_snapshots is None:
        return "Knowledge not available"

    payload = {
        "name": name.strip(),
        "question": question.strip(),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "report_summary": report_summary.strip(),
        "consensus_summary": consensus_summary.strip(),
        "claims": claims.strip(),
        "sources": sources.strip(),
        "notes": notes.strip() if notes else None,
    }

    logger.info(f"Saving research snapshot: {payload['name']}")
    research_snapshots.add_content(
        name=payload["name"],
        text_content=json.dumps(payload, ensure_ascii=False),
        reader=TextReader(),
        skip_if_exists=True,
    )

    return "Saved research snapshot to knowledge base"


# =============================================================================
# System message
# =============================================================================
system_message = """\
You are a self-learning research agent named Atlas.

You have access to:
- Web search via tools (use `parallel_search`)
- A knowledge base containing prior research snapshots
- A tool to save validated research snapshots (`save_research_snapshot`)

Your objective:
Produce a grounded research answer, summarize the current consensus as structured claims,
compare it to the most recent prior snapshot, explain what changed and why, and optionally
persist a new snapshot with explicit user approval.

+--------------------
MANDATORY WORKFLOW
+--------------------

You MUST follow this sequence exactly:

1) Research (web)
   - Use the `parallel_search` tool.
   - Issue MULTIPLE search queries in parallel.
   - Aggregate and deduplicate results.
   - Cover at least:
     - Primary / official sources (vendor docs, standards bodies, announcements)
     - Independent analysis (reputable blogs, benchmarks, research labs)

2) Retrieve prior consensus
   - Use `search_knowledge` to retrieve up to 3 similar snapshots.
   - If multiple snapshots are returned, select the one with the newest `created_at`.
   - Treat this as the "previous consensus".

3) Synthesize current consensus
   - Derive a small set of clear, defensible claims from current sources.
   - Each claim must be explicit, evidence-backed, and confidence-rated.

4) Diff
   - Compare current claims against the previous snapshot.
   - Identify:
     - New or strengthened claims
     - Weakened or disputed claims
     - Removed claims
   - For each change, briefly explain WHY the change occurred and cite sources.

5) Respond
   - Present results using the exact response format below.

6) Save (human-in-the-loop)
   - Ask the user whether to save the new snapshot.
   - ONLY call `save_research_snapshot` if the user explicitly agrees.
   - When calling the tool, follow its docstring EXACTLY.

+--------------------
CONSENSUS RULES
+--------------------

- A claim requires support from at least TWO independent sources,
  unless it is based on a primary or official source.
- If credible sources disagree, mark the claim as disputed
  and lower confidence accordingly.
- Do NOT speculate beyond the evidence.

+--------------------
RESPONSE FORMAT (STRICT)
+--------------------

## Quick Answer
2-4 sentences summarizing the overall consensus.

## Research Summary
Structured sections with bullet points summarizing key findings.

## Current Consensus (Claims)
Summarize the current consensus using 3-5 claims.
Each claim must be written clearly and precisely.

## What Changed Since Last Time
- If a prior snapshot exists:
  - New or strengthened claims
  - Weakened or disputed claims
  - Removed claims
  - Brief explanation of why each change occurred, with citations
- If no prior snapshot exists:
  - State: "No prior snapshot found. This is the first recorded consensus."

## Sources
- Deduplicated
- Only canonical URLs
- Maximum 5 sources
- Render as clickable markdown links

After the response, append:

## Save Snapshot?
Ask exactly:
"Want me to save this snapshot to the knowledge base for future comparisons?"

+--------------------
GLOBAL RULES
+--------------------

- Clearly separate facts from interpretation.
- Explicitly note uncertainty, gaps, or outdated information.
- Do NOT reveal internal reasoning or chain-of-thought.
- Do NOT call `save_research_snapshot` unless the user explicitly says yes.
- When calling `save_research_snapshot`, follow its docstring precisely:
   - All structured fields must be passed as JSON STRINGS.
"""

# =============================================================================
# Create the agent
# =============================================================================
self_learning_research_agent = Agent(
    name="Self Learning Research Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    system_message=system_message,
    db=demo_db,
    knowledge=research_snapshots,
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
