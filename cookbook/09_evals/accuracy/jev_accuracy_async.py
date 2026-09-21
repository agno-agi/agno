"""Score three supplied answers concurrently with one Jev async client.

Requires Python 3.10+, typesafe-sdk, and TYPESAFE_API_KEY. Results are displayed
after the requests complete, so concurrent output does not interleave.
"""

import asyncio

from rich.pretty import pprint

from agno.run.agent import RunInput, RunOutput
from agno.run.base import RunStatus
from agno.scorer.typesafe import JevAccuracyScorer

QUESTION = "What are the requirements for a refund?"
REFERENCE = "Request a refund within 30 days of purchase and provide the receipt."
ANSWERS = (
    (
        "paraphrase",
        "You have 30 days from purchase to ask for a refund, and you'll need your receipt.",
    ),
    ("incomplete", "Refunds are available within 30 days of purchase."),
    ("contradiction", "Refunds are available for 90 days without a receipt."),
)

scorer = JevAccuracyScorer(pass_threshold=0.8)


async def main() -> None:
    scores = await asyncio.gather(
        *(
            scorer.ascore(
                RunOutput(
                    input=RunInput(input_content=QUESTION),
                    content=answer,
                    status=RunStatus.completed,
                ),
                expected=REFERENCE,
            )
            for _, answer in ANSWERS
        )
    )
    for (label, answer), score in zip(ANSWERS, scores):
        pprint({"case": label, "answer": answer, "score": score})


if __name__ == "__main__":
    asyncio.run(main())
