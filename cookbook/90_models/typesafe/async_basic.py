"""
Jev Async Basic
===============

Classify several reviews concurrently using one agent and the async SDK.
Independent topic flags allow a review to mention several topics while keeping
the output schema fixed. Each request uses a separate session.

Requires Python 3.10+, typesafe-sdk, and TYPESAFE_API_KEY.
"""

import asyncio
from io import StringIO
from typing import Annotated, Literal

from pydantic import BaseModel
from rich.console import Console
from rich.pretty import pprint
from typesafe_sdk import Choice, Noul

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.typesafe import Jev, JevField
from agno.run.base import RunStatus


class Topics(BaseModel):
    price: Annotated[
        bool,
        JevField(
            Noul(instructions="Does the review in state.input discuss price?"),
            threshold=0.7,
        ),
    ]
    quality: Annotated[
        bool,
        JevField(
            Noul(
                instructions="Does the review in state.input discuss product quality?"
            ),
            threshold=0.7,
        ),
    ]
    shipping: Annotated[
        bool,
        JevField(
            Noul(
                instructions="Does the review in state.input discuss shipping or delivery?"
            ),
            threshold=0.7,
        ),
    ]
    support: Annotated[
        bool,
        JevField(
            Noul(
                instructions="Does the review in state.input discuss customer support?"
            ),
            threshold=0.7,
        ),
    ]


class Review(BaseModel):
    sentiment: Annotated[
        Literal["positive", "negative", "mixed"],
        JevField(
            Choice(
                instructions="What is the overall sentiment of the review in state.input?",
                criteria={
                    "positive": "Overall favorable",
                    "negative": "Overall unfavorable",
                    "mixed": "Mixed, neutral, or no clear preference",
                },
            )
        ),
    ]
    topics: Topics
    would_recommend: Annotated[
        bool,
        JevField(
            Noul(
                instructions="Does the reviewer in state.input say or clearly imply they would recommend the product?"
            ),
            threshold=0.7,
        ),
    ]


agent = Agent(model=Jev(), output_schema=Review, db=InMemoryDb())

REVIEWS = [
    "Great kettle, boils fast and looks good. A bit pricey, but I would buy it again.",
    "Arrived two weeks late and the box was crushed. Support never answered my emails.",
    "It works. Nothing special, nothing wrong.",
]


async def main() -> None:
    # Separate consoles keep concurrent response panels from interleaving.
    buffers = [StringIO() for _ in REVIEWS]
    await asyncio.gather(
        *(
            agent.aprint_response(
                review,
                session_id=f"review-{index}",
                console=Console(file=buffers[index]),
            )
            for index, review in enumerate(REVIEWS)
        )
    )
    console = Console()
    for index, buffer in enumerate(buffers):
        console.print(buffer.getvalue(), markup=False, highlight=False)
        run = await agent.aget_last_run_output(session_id=f"review-{index}")
        if run is None:
            continue
        if run.status == RunStatus.completed:
            review = Review.model_validate(run.content)
            pprint(
                {
                    "mentioned_topics": [
                        name
                        for name, mentioned in review.topics.model_dump().items()
                        if mentioned
                    ]
                }
            )
        pprint(run.model_provider_data)


if __name__ == "__main__":
    asyncio.run(main())
