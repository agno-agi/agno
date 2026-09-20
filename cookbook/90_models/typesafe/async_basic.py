"""
Jev Async Basic
===============

Demonstrates Jev filling an `output_schema` with `arun`, over several inputs at once.

One agent is reused for every input. Jev answers in roughly a tenth of a second, so
a batch of classifications finishes in about the time of the slowest one.

Requirements:
- `pip install typesafe-sdk` (Python 3.10+)
- export TYPESAFE_API_KEY="your_api_key"
"""

import asyncio
from typing import List, Literal

from agno.agent import Agent
from agno.models.typesafe import Jev
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define the Questions
# ---------------------------------------------------------------------------


class Review(BaseModel):
    sentiment: Literal["positive", "negative", "mixed"] = Field(
        description="What is the overall sentiment of the review?"
    )
    # One yes/no question per topic: "{}" is filled with each value
    topics: List[Literal["price", "quality", "shipping", "support"]] = Field(
        default_factory=list, description="Does the review talk about {}?"
    )
    would_recommend: bool = Field(
        description="Does the reviewer say or clearly imply they would recommend the product?"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Jev(), output_schema=Review)

REVIEWS = [
    "Great kettle, boils fast and looks good. A bit pricey, but I would buy it again.",
    "Arrived two weeks late and the box was crushed. Support never answered my emails.",
    "It works. Nothing special, nothing wrong.",
]

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------


async def main() -> None:
    runs = await asyncio.gather(*(agent.arun(review) for review in REVIEWS))
    for review, run in zip(REVIEWS, runs):
        result: Review = run.content
        print(review)
        print(
            f"  sentiment={result.sentiment}  topics={result.topics}  would_recommend={result.would_recommend}"
        )
        print(f"  least certain answer: {run.model_provider_data['confidence']}\n")


if __name__ == "__main__":
    asyncio.run(main())
