"""Generate an answer, then use Jev to score it against a reference.

Requires Python 3.10+, typesafe-sdk, openai, TYPESAFE_API_KEY, and OPENAI_API_KEY.
See cookbook/09_evals/accuracy/jev_accuracy_*.py for supplied answers,
concurrent scoring, and an eval suite. AccuracyEval(model=Jev()) is unsupported;
JevAccuracyScorer preserves probabilities instead of producing a 1-10 grade.
"""

from rich.pretty import pprint

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.scorer.typesafe import JevAccuracyScorer

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Refunds must be requested within 30 days of purchase and require a receipt. Answer briefly.",
    cache_session=True,
)
scorer = JevAccuracyScorer(pass_threshold=0.8)

if __name__ == "__main__":
    agent.print_response("What are the requirements for a refund?")
    response = agent.get_last_run_output()
    if response is None:
        raise RuntimeError("No response was saved for scoring")
    pprint(
        scorer.score(
            response,
            expected="Request a refund within 30 days of purchase and provide the receipt.",
        )
    )
