"""
Can We Ship the Cheaper Model?
==============================
The question every cost review asks, answered with a distribution instead of
a vibe: run the SAME environment on the current model and the candidate, and
diff the two results task by task.

Three pieces of the API meet here:

- Task.from_jsonl loads the task set from a file a team can own in git.
  Validation is strict: an unknown key (say, a misspelled "expected_output"
  column) raises with the line number instead of silently making every
  expected None.
- run_rollouts(env, model=...) swaps the policy for one run without touching
  the env. The environment fingerprint stays identical -- the tasks, scorer,
  and prompts did not move -- while the policy fingerprint tracks the model
  that actually ran. That split is what makes the diff meaningful.
- results.save() / EnvironmentRunResult.load() / candidate.diff(baseline) close the
  loop across time: save a baseline today, diff a candidate against it next
  week. diff raises MismatchError if the environment drifted in between,
  so you cannot accidentally compare across different task sets. Note the
  saved artifact contains full transcripts in plain text -- treat it like
  any other file holding your production prompts.
"""

from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, EnvironmentRunResult, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Create Environment
# ---------------------------------------------------------------------------


class Triage(BaseModel):
    category: str  # one of: billing, bug, feature_request, account_access
    reasoning: str


def label_matches(run, expected):
    return run.content.category.strip().lower() == expected


_TASKS_PATH = Path(__file__).parent / "tasks" / "support_triage.jsonl"
_OUTPUT_DIR = Path(__file__).parent / "data" / "generated"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    output_schema=Triage,
    instructions=(
        "Triage the customer message into exactly one category: billing, "
        "bug, feature_request, or account_access."
    ),
)

env = Environment(
    name="support-triage",
    agent=agent,
    tasks=Task.from_jsonl(_TASKS_PATH),
    scorer=CodeScorer(label_matches),
)

# ---------------------------------------------------------------------------
# Baseline, Candidate, Diff
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline_path = _OUTPUT_DIR / "triage_baseline.json"

    # Baseline: the model the agent ships with today.
    baseline = run_rollouts(env, k=8)
    print(baseline)
    baseline.save(baseline_path)
    print(f"baseline saved to {baseline_path}")
    print()

    # Candidate: same env, cheaper model. Only the policy changes; the
    # stamped policy_fingerprint is computed from the model that actually
    # ran, so the two runs are distinguishable forever.
    candidate = run_rollouts(env, k=8, model=OpenAIResponses(id="gpt-5-mini"))
    print(candidate)
    print()

    # Reload the baseline as a second session would, then diff.
    baseline = EnvironmentRunResult.load(baseline_path)
    diff = candidate.diff(baseline)
    print(diff)

    # The decision, in two numbers.
    baseline_rate = baseline.summary()["pass_rate"]
    candidate_rate = candidate.summary()["pass_rate"]
    print()
    print(f"baseline pass rate:  {baseline_rate}")
    print(f"candidate pass rate: {candidate_rate}")
