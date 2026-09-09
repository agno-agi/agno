"""
Rejection Sampling - Step Rewards
=================================

Math-Shepherd-style Monte-Carlo process rewards. basic.py labels a whole
trace by its outcome: the final answer verifies or the trace is dropped.
Here the same pure-code verifier is pushed down into the trace: a solver
writes a stepwise solution, and each step prefix is scored by running K
continuation rollouts from it - the step's reward is the fraction of
rollouts that still reach the verified gold. Outcome supervision distilled
into per-step process labels, with no judge and no per-step human
annotation.

One solution gets a deliberately corrupted middle step, the folder's usual
designed-to-fail element: the score cliff localizes the exact step where
reasoning breaks, and the steps after it show whether rollouts recover
from a poisoned prefix or stay poisoned.

Problems and golds are imported from basic.py; every gold was verified by
hand and by a script before being committed.
"""

import json
from pathlib import Path
from typing import Optional

from agno.agent import Agent, RunOutput
from basic import PROBLEMS
from pydantic import BaseModel, Field
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class StepwiseSolution(BaseModel):
    steps: list[str] = Field(
        ...,
        description="at most 5 solution steps, each one sentence with one operation",
    )
    final_answer: int = Field(..., description="the final integer answer alone")


class Continuation(BaseModel):
    final_answer: int = Field(
        ..., description="the final integer answer the completed solution reaches"
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
K = 3  # continuation rollouts per step prefix
SHARP_DROP = 0.5  # score fall (vs the previous step) that flags a broken step

# One solution gets a hand-written wrong step spliced in after generation:
# the daily total is restated correctly (12 * 6 = 72) but 72 - 15 is
# miscomputed as 67 (it is 57). A faithful continuation of this prefix
# lands on 67 * 5 = 335 instead of the gold 285.
CORRUPT_ID = "p1"
CORRUPT_STEP_INDEX = 1
CORRUPTED_STEP = (
    "Each day the bakery bakes 12 * 6 = 72 muffins; setting aside 15 for "
    "staff leaves 72 - 15 = 67 muffins sold per day."
)


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
solver = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "Solve the problem in numbered steps. Use at most 5 steps. Each "
        "step is one sentence performing one operation or one intermediate "
        "computation. Then give the final integer answer."
    ),
    output_schema=StepwiseSolution,
)

# Default sampling temperature: the K rollouts from each prefix must vary,
# or the fraction-correct score degenerates to 0 or 1 by construction.
# The instructions pin the completer to faithful continuation. The MC
# estimate targets P(gold | prefix continued as written); a completer that
# audits and repairs the prefix measures recoverability instead, and wrong
# steps stop scoring low.
rollout = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You are given a problem and the first steps of a solution. "
        "Continue from those steps and finish the solution, then give the "
        "final integer answer. Treat the given steps as fixed: build on "
        "them exactly as written, even if you believe one contains an "
        "error. Do not audit, correct, or restart them."
    ),
    output_schema=Continuation,
)


def build_rollout_input(prompt: str, prefix: list[str]) -> str:
    steps_text = "\n".join(f"Step {i}: {s}" for i, s in enumerate(prefix, start=1))
    return f"Problem:\n{prompt}\n\nSolution so far:\n{steps_text}"


def first_sharp_drop(scores: list[float]) -> Optional[int]:
    # The baseline before step 1 is 1.0: for a problem the model can solve,
    # an opening step that already caps the solve rate is itself the break.
    prev = 1.0
    for i, score in enumerate(scores):
        if prev - score >= SHARP_DROP:
            return i
        prev = score
    return None


# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "prm_rows.jsonl"

    rows = []
    total_rollouts = 0

    for problem in PROBLEMS[:3]:
        run: RunOutput = solver.run(problem["prompt"])
        solution: StepwiseSolution = run.content
        steps = list(solution.steps)
        if problem["id"] == CORRUPT_ID and len(steps) >= 2:
            steps[CORRUPT_STEP_INDEX] = CORRUPTED_STEP

        step_scores = []
        for prefix_len in range(1, len(steps) + 1):
            prefix = steps[:prefix_len]
            passed = 0
            for _ in range(K):
                rollout_run: RunOutput = rollout.run(
                    build_rollout_input(problem["prompt"], prefix)
                )
                continuation: Continuation = rollout_run.content
                # Same pure-code verifier as basic.py: integer equality
                # against the hand-checked gold.
                if continuation.final_answer == problem["gold"]:
                    passed += 1
            total_rollouts += K
            step_scores.append(passed / K)

        rows.append(
            {
                "problem": problem["prompt"],
                "steps": steps,
                "step_scores": step_scores,
                "k": K,
            }
        )

        corrupted = (
            " (step 2 deliberately corrupted)" if problem["id"] == CORRUPT_ID else ""
        )
        print(f"{problem['id']}{corrupted}:")
        for i, (step, score) in enumerate(zip(steps, step_scores), start=1):
            text = step if len(step) <= 68 else step[:65] + "..."
            print(f"  step {i}: {score:.2f}  {text}")
        drop = first_sharp_drop(step_scores)
        if drop is None:
            print("  no sharp drop: every prefix keeps rollouts on the gold answer")
        else:
            prev = step_scores[drop - 1] if drop > 0 else 1.0
            print(
                f"  first sharp drop at step {drop + 1} "
                f"({prev:.2f} -> {step_scores[drop]:.2f}) - reasoning breaks here"
            )
        print()

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print("example prm row:")
    pprint(rows[0] if rows else None)

    total_steps = sum(len(row["steps"]) for row in rows)
    print()
    print(
        f"wrote {len(rows)} rows, scored {total_steps} steps, "
        f"ran {total_rollouts} rollouts"
    )
