"""Competitive Market Brief with Gemini 3.8 Flash.

A research desk that turns an open-ended question about a company or product
into a structured, source-backed brief.

The pattern combines three things Gemini 3.8 Flash is well suited for:

- Google Search grounding, so claims come from current pages rather than
  training data
- URL context, so the model reads the specific pages it finds
- A Pydantic `output_schema`, so the brief lands as typed data you can store,
  diff between runs, or feed into another agent

Because 3.8 Flash keeps the discounted pricing of 3.7 Flash, a research loop
like this stays cheap enough to run on every company in a watchlist.

Run `uv pip install -U google-genai agno` to install dependencies.
Export `GOOGLE_API_KEY` before running.
"""

import asyncio
from typing import List, Literal, Optional

from agno.agent import Agent
from agno.models.google import Gemini
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------


class Source(BaseModel):
    """A page the brief drew from."""

    title: str = Field(description="Title of the page or article")
    url: str = Field(description="Full URL of the source")
    takeaway: str = Field(description="The single most useful fact from this source")


class Competitor(BaseModel):
    """A rival product or company worth tracking."""

    name: str = Field(description="Competitor name")
    positioning: str = Field(
        description="How the competitor positions itself, in one sentence"
    )
    edge: str = Field(description="Where the competitor is stronger than the subject")
    gap: str = Field(description="Where the competitor is weaker than the subject")


class MarketBrief(BaseModel):
    subject: str = Field(description="The company or product the brief is about")
    one_liner: str = Field(description="What the subject does, in a single sentence")

    momentum: Literal["accelerating", "steady", "slowing", "unclear"] = Field(
        description="Current trajectory of the subject"
    )
    momentum_evidence: str = Field(
        description="The specific, dated evidence behind the momentum rating"
    )

    recent_developments: List[str] = Field(
        description="Notable events from the last few months, newest first"
    )
    competitors: List[Competitor] = Field(
        description="Two to four competitors worth tracking"
    )

    open_questions: List[str] = Field(
        description="What a researcher still needs to find out"
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="How well sourced this brief is"
    )
    caveat: Optional[str] = Field(
        description="Anything that undercuts the brief, such as thin or dated sourcing",
        default=None,
    )

    sources: List[Source] = Field(description="Pages the brief drew from")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# search=True gives the model Google Search grounding.
# url_context=True lets it read the pages that search surfaces.
market_analyst = Agent(
    name="Market Analyst",
    model=Gemini(id="gemini-3.8-flash", search=True, url_context=True),
    output_schema=MarketBrief,
    instructions="""\
You are a market analyst. Produce briefs a product team can act on.

## Method

- Search before you answer. Never rely on what you remember about a company.
- Read the pages you find rather than summarizing search snippets.
- Prefer primary sources: company blogs, filings, release notes, docs.
- Attach a date to every claim about momentum or recent developments.

## Rules

- If sourcing is thin or dated, say so in the caveat and lower the confidence.
- Never invent a competitor, a funding round, or a launch to fill out the schema.
- Keep positioning and edge/gap statements to one sentence each.
- No emojis.\
""",
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def print_brief(brief: MarketBrief) -> None:
    print(f"\n{brief.subject} - {brief.one_liner}")
    print(f"Momentum: {brief.momentum} ({brief.confidence} confidence)")
    print(f"  {brief.momentum_evidence}")

    print("\nRecent developments")
    for development in brief.recent_developments:
        print(f"  - {development}")

    print("\nCompetitors")
    for competitor in brief.competitors:
        print(f"  {competitor.name}: {competitor.positioning}")
        print(f"    Edge: {competitor.edge}")
        print(f"    Gap:  {competitor.gap}")

    print("\nOpen questions")
    for question in brief.open_questions:
        print(f"  - {question}")

    if brief.caveat:
        print(f"\nCaveat: {brief.caveat}")

    print("\nSources")
    for source in brief.sources:
        print(f"  - {source.title}: {source.url}")
        print(f"    {source.takeaway}")


async def brief_watchlist(subjects: List[str]) -> List[MarketBrief]:
    """Research a whole watchlist concurrently, reusing the one agent."""
    runs = await asyncio.gather(
        *(
            market_analyst.arun(f"Write a market brief on {subject}.")
            for subject in subjects
        )
    )
    return [run.content for run in runs]


if __name__ == "__main__":
    # --- Sync: a single brief ---
    run = market_analyst.run(
        "Write a market brief on the open-source AI agent framework Agno."
    )
    print_brief(run.content)

    # --- Async: a watchlist, researched in parallel ---
    watchlist = [
        "the vector database company Qdrant",
        "the observability company LangSmith",
    ]
    for brief in asyncio.run(brief_watchlist(watchlist)):
        print_brief(brief)
