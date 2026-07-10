"""
Text Multilabel Classification - Hierarchical
=============================================

Tags drawn from a two-level taxonomy: a parent category and a child within
that category. Useful when the label space is large and naturally nested
(news topics, product catalogs, support categories).
"""

from typing import List, Literal

from agno.agent import Agent, RunOutput  # noqa
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa

ParentTopic = Literal["sports", "politics", "tech", "business", "health"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class HierarchicalTag(BaseModel):
    parent: ParentTopic
    child: str = Field(
        ...,
        description=(
            "Specific subtopic within the parent. Examples: "
            "sports -> football | basketball | tennis; "
            "tech -> ai | hardware | security; "
            "business -> markets | startups | regulation."
        ),
    )


class Tagging(BaseModel):
    tags: List[HierarchicalTag]


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Tag the news article with all parent/child pairs it covers. The child must
be a meaningful subtopic of the parent, and should reflect what the article
is actually about - not every entity mentioned in passing.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=Tagging,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "The Fed held rates steady as markets reacted to a surprise jobs report. "
        "Tech stocks led the rally, with AI chipmakers up 4 percent.",
        "Manchester United fired their head coach after a third consecutive loss. "
        "The board is reportedly courting a replacement from Spain.",
    ]
    for text in samples:
        run: RunOutput = agent.run(text)
        pprint({"input": text, "result": run.content})
