"""
Judge Gate
==========
ScorerVerifier turns any agno.scorer into an in-loop gate: the same grading interface
used by offline evals, applied while the run is still alive. Here a numeric LLM judge
must score the answer at least 8/10 or the model keeps working.

The scorer owns its threshold; the verifier just holds the run to the scorer's verdict.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.scorer import JudgeScorer
from agno.verifiers import ScorerVerifier

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

judge = JudgeScorer(
    model=OpenAIResponses(id="gpt-5.5"),
    criteria=(
        "The explanation is aimed at a newcomer: no unexplained jargon, one concrete "
        "example, and under 150 words."
    ),
    mode="numeric",
    threshold=8,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    verifiers=[ScorerVerifier(judge)],
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

output = agent.run("Explain what a race condition is.")

print("status:", output.status)
print("verification:", output.verification.status, "/", output.verification.stop_reason)
for attempt in output.verification.attempts:
    for verdict in attempt.verdicts:
        detail = verdict.data or {}
        print(
            "attempt", attempt.index, "-> passed:", verdict.passed, "| detail:", detail
        )
print()
print(output.content)
