"""
Swarm Team — a verified k-model ensemble
========================================

A k-LLM ensemble that doesn't just average. The same question goes to
several web-search agents on different providers (OpenAI, Anthropic, and
Google when configured). A dedicated Verifier then re-checks the key claims
against their cited sources before the leader synthesizes — so a confident
but wrong citation from one model gets caught instead of voted in.

The flow:
1. Broadcast the question to the proposers — same question, different models.
2. The leader collects their claims + citations and calls the Verifier, which
   re-reads the cited sources and returns SUPPORTED / UNSUPPORTED verdicts.
3. The leader synthesizes a grounded answer, flags unsupported claims, and
   gives a confidence read based on BOTH model agreement and verification.

All members and the Verifier share one `web_provider` (Parallel MCP) — one
session, many perspectives. The Gemini proposer is added when GOOGLE_API_KEY
is set.

Required env:
  OPENAI_API_KEY, ANTHROPIC_API_KEY
Optional env:
  GOOGLE_API_KEY    (adds a third proposer)
  PARALLEL_API_KEY  (raises the Parallel MCP rate ceiling)
"""

from os import getenv

from agents.web_search import web_provider
from agno.agent import Agent
from agno.team import Team
from agno.team.mode import TeamMode
from db import get_db
from settings import anthropic_model, default_model, gemini_model

_PROPOSER_INSTRUCTIONS = """\
Answer the question using current information from the web.

Call query_web for any non-trivial factual claim, and cite the URL you used
as a plain link right next to the claim it supports. Prefer recent,
authoritative sources. If the search returns nothing useful, say so plainly
rather than guessing.
"""


# ---------------------------------------------------------------------------
# Proposers — same question, different providers
# ---------------------------------------------------------------------------
web_search_openai = Agent(
    id="swarm-openai",
    name="Proposer (OpenAI)",
    role="Answer the question with cited web research using OpenAI gpt-5.5.",
    model=default_model(),
    db=get_db(),
    tools=web_provider.get_tools(),
    instructions=_PROPOSER_INSTRUCTIONS + "\n\n" + web_provider.instructions(),
    markdown=True,
)

web_search_anthropic = Agent(
    id="swarm-anthropic",
    name="Proposer (Anthropic)",
    role="Answer the question with cited web research using Anthropic claude-opus-4-7.",
    model=anthropic_model(),
    db=get_db(),
    tools=web_provider.get_tools(),
    instructions=_PROPOSER_INSTRUCTIONS + "\n\n" + web_provider.instructions(),
    markdown=True,
)

_members = [web_search_openai, web_search_anthropic]

# Third provider — added when Gemini is configured, for cross-provider diversity.
if getenv("GOOGLE_API_KEY"):
    web_search_gemini = Agent(
        id="swarm-google",
        name="Proposer (Google)",
        role="Answer the question with cited web research using Google gemini-3.5-flash.",
        model=gemini_model(),
        db=get_db(),
        tools=web_provider.get_tools(),
        instructions=_PROPOSER_INSTRUCTIONS + "\n\n" + web_provider.instructions(),
        markdown=True,
    )
    _members.append(web_search_gemini)


# ---------------------------------------------------------------------------
# Verifier — re-checks the proposers' claims against their cited sources
# ---------------------------------------------------------------------------
_VERIFIER_INSTRUCTIONS = """\
You fact-check claims against their cited sources. You are given a list of
claims, each with one or more source URLs.

For each claim:
1. Call query_web to re-read the cited source and check whether it actually
   supports the claim. Frame the query around the specific URL and claim,
   e.g. "According to <url>, is it true that <claim>? Quote the passage."
2. Return a verdict — SUPPORTED (the source backs it, with the quoted
   passage), UNSUPPORTED (the source does not back it or contradicts it), or
   UNVERIFIABLE (source unreachable or irrelevant).

Be skeptical. A plausible claim with a citation that does not actually
contain it is exactly what you are here to catch. Return a short per-claim
list of verdicts with the quoted evidence.
"""

# A stateless checker (no db/memory) — it's a pure function of (claims -> verdicts).
verifier = Agent(
    id="swarm-verifier",
    name="Verifier",
    model=default_model(),
    tools=web_provider.get_tools(),
    instructions=_VERIFIER_INSTRUCTIONS,
    markdown=True,
)


async def verify_claims(claims: str) -> str:
    """Re-check claims against their cited sources and return per-claim verdicts.

    Args:
        claims: The claims to verify, each paired with its source URL(s), as text.
    """
    try:
        result = await verifier.arun(input=claims)
        return result.content or "Verifier returned no output."
    except Exception as exc:
        return f"Verification unavailable ({type(exc).__name__}); treat claims as unverified."


# ---------------------------------------------------------------------------
# Team — broadcast to proposers, verify, then synthesize
# ---------------------------------------------------------------------------
SWARM_INSTRUCTIONS = """\
You lead a verified research swarm. Your members are proposer agents on
different models; broadcast mode sends them the question and returns their
cited answers.

Once you have the proposers' answers:
1. Collect the key claims and the source URL each one cites.
2. Call verify_claims ONCE, passing those claims with their URLs, to
   fact-check them against the sources.
3. Synthesize the final answer with this structure:
   - **Answer** — lead with what the proposers agree on AND the Verifier
     marked SUPPORTED.
   - **Flagged** — any claim the Verifier marked UNSUPPORTED or UNVERIFIABLE.
     Do not state these as fact; drop them or clearly caveat them.
   - **Disagreement** — one line per point where the models diverged, with a
     one-sentence reason for each side.
   - **Sources** — the merged, de-duplicated URLs that survived verification.
   - **Confidence: high | medium | low** — judged on BOTH model agreement and
     how many key claims verified. One sentence on why.
"""


swarm = Team(
    id="swarm",
    name="Swarm",
    mode=TeamMode.broadcast,
    model=default_model(),
    db=get_db(),
    members=_members,
    tools=[verify_claims],
    instructions=SWARM_INSTRUCTIONS,
    show_members_responses=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
