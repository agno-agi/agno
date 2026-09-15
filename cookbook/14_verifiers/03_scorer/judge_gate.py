"""
Judge Gate
==========
ScorerVerifier turns any agno.scorer into an in-loop gate: the same grading interface
used by offline evals, applied while the run is still alive. Here a numeric LLM judge
must score the answer at least 8/10 or the model keeps working.

The scorer owns its threshold; the verifier just holds the run to the scorer's verdict.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.scorer import JudgeScorer
from agno.verifiers import ScorerVerifier

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

judge = JudgeScorer(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    criteria=(
        "The explanation is aimed at a newcomer: no unexplained jargon, one concrete "
        "example, and under 150 words."
    ),
    mode="numeric",
    threshold=8,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=InMemoryDb(),
    verifiers=[ScorerVerifier(judge)],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("Explain what a race condition is.")

    run_output = agent.get_last_run_output()
    verification = run_output.verification
    print(
        f"\nVerification: {verification.status.value} / {verification.stop_reason.value}"
    )
    for attempt in verification.attempts:
        for verdict in attempt.verdicts:
            result = "PASS" if verdict.passed else "FAIL"
            # The judge's normalized score and its reasoning ride on Verdict.detail.
            score = (verdict.detail or {}).get("value")
            print(f"Attempt {attempt.index}: {result} | score: {score:.2f}")
