"""
Judge Gate: a scorer as the completion check
============================================
ScorerVerifier bridges the shipped agno.scorer surface into the loop. One JudgeScorer can
grade a run offline in an eval and gate completion here; the judge owns the pass rule
(numeric mode, threshold 8 of 10), and ScorerVerifier passes iff the score passed.

The task asks for something a first answer often gets only half right, so a continuation
with the judge's reason is likely.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.scorer import JudgeScorer
from agno.verify import (
    VERIFICATION_NOTICE,
    ScorerVerifier,
    VerifierLimits,
    run_verified,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[VERIFICATION_NOTICE],
)

judge = JudgeScorer(
    model=OpenAIResponses(id="gpt-5.5"),
    criteria=(
        "The answer is a single limerick (exactly five lines, AABBA rhyme) about a database index, "
        "mentions both reads and writes, and contains no preamble or commentary."
    ),
    mode="numeric",
    threshold=8,
)

result = run_verified(
    agent,
    "Write a limerick about a database index.",
    verifiers=[ScorerVerifier(judge, name="limerick_judge")],
    limits=VerifierLimits(max_continuations=2),
)

print("status:", result.status)
for attempt in result.attempts:
    for verdict in attempt.verdicts:
        value = (verdict.data or {}).get("value")
        print(
            f"attempt {attempt.index} [{'PASS' if verdict.passed else 'FAIL'}] {verdict.name} value={value}"
        )
        if not verdict.passed:
            print("  " + verdict.report[:200])
print()
print(result.output.content)
