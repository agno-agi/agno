"""
Unverified: the named outcome for a check that never passes
===========================================================
A run that exhausts its continuation budget without passing does not end "completed" as
far as the caller is concerned: it ends `unverified`, with every attempt's verdicts kept.

This example uses an impossible check so the outcome is guaranteed, and shows what a caller
reads back: stop_reason, each attempt's run_id (every continuation is a forked sibling run),
and the per-attempt metrics to sum for the cost of the whole run.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.verify import VERIFICATION_NOTICE, VerifierLimits, run_verified

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[VERIFICATION_NOTICE],
)


def impossible(run):
    return "the answer must be exactly 41 words long and contain no vowels"


result = run_verified(
    agent,
    "Say hello in one short sentence.",
    verifiers=[impossible],
    limits=VerifierLimits(max_continuations=1),
)

print("status:", result.status)
print("stop_reason:", result.stop_reason)
print("attempts:", len(result.attempts))

total_tokens = 0
for attempt in result.attempts:
    metrics = attempt.metrics
    tokens = getattr(metrics, "total_tokens", 0) or 0
    total_tokens += tokens
    print(f"attempt {attempt.index}: run_id={attempt.run_id} tokens={tokens}")
    for verdict in attempt.verdicts:
        print(
            f"  [{'PASS' if verdict.passed else 'FAIL'}] {verdict.name}: {verdict.report[:80]}"
        )
print("total tokens across attempts:", total_tokens)

# The RunOutput still says completed. Read VerifiedRun.status, not output.status.
print("output.status:", result.output.status)
print(
    "final record on the returned output:",
    result.output.metadata["verification"]["status"],
)
