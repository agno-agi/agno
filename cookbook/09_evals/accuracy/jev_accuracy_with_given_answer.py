"""Score supplied answers against a reference with Jev.

Requires Python 3.10+, typesafe-sdk, and TYPESAFE_API_KEY. No generative model
is needed. The score is a correctness probability; 0.8 is a starting threshold
to calibrate on your own examples, not a measured accuracy guarantee.
"""

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

if __name__ == "__main__":
    for label, answer in ANSWERS:
        run = RunOutput(
            input=RunInput(input_content=QUESTION),
            content=answer,
            status=RunStatus.completed,
        )
        score = scorer.score(run, expected=REFERENCE)
        pprint({"case": label, "answer": answer, "score": score})
