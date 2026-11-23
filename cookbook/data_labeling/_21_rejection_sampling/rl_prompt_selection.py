"""
Rejection Sampling - RL Prompt Selection
========================================

Use pass rates to pick training prompts in the learning zone. Sample K
traces per problem against a verified gold: problems the model always
solves teach nothing, problems it never solves give no reward signal.
Keep only prompts with 0 < correct < K - the band where an RL loop (or
curriculum) actually gets gradient.

The problem set deliberately spans trivial arithmetic to problems designed
to exceed what the model can compute in its head, so both cut lines get
exercised. The printout shows designed difficulty next to observed pass
rate - reasoning models routinely beat difficulty intuitions, which is
exactly why pass rates are measured instead of guessed. Every gold was
verified by hand and by a script before being committed.
"""

import json
from pathlib import Path

from agno.agent import Agent, RunOutput
from pydantic import BaseModel, Field
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class Solution(BaseModel):
    reasoning: str = Field(..., description="step by step reasoning")
    final_answer: int = Field(..., description="the final integer answer alone")


# ---------------------------------------------------------------------------
# Problems
# ---------------------------------------------------------------------------
# "designed" records the intended difficulty; the printout shows observed
# reality next to it, which is the point of measuring instead of guessing.
PROBLEMS = [
    {
        "id": "r1",
        "designed": "trivial",
        "prompt": "What is 7 + 5?",
        "gold": 12,
    },
    {
        "id": "r2",
        "designed": "trivial",
        "prompt": "What is 12 * 11?",
        "gold": 132,
    },
    {
        "id": "r3",
        "designed": "easy",
        "prompt": (
            "A box holds 24 pencils. A school orders 17 boxes and hands out "
            "350 pencils. How many pencils remain?"
        ),
        "gold": 58,
    },
    {
        "id": "r4",
        "designed": "medium",
        "prompt": (
            "How many integers n with 1 <= n <= 500 have a digit sum divisible by 7?"
        ),
        "gold": 68,
    },
    {
        "id": "r5",
        "designed": "medium",
        "prompt": ("Let x0 = 7 and x_{n+1} = (x_n^2 + 1) mod 1013. What is x_60?"),
        "gold": 718,
    },
    {
        "id": "r6",
        "designed": "hard",
        "prompt": "What is the 613th prime number?",
        "gold": 4517,
    },
    {
        "id": "r7",
        "designed": "hard",
        "prompt": "What is 73482915684921637 * 91827364550918273?",
        "gold": 6747742486863689476416508396372901,
    },
    {
        "id": "r8",
        "designed": "impossible",
        "prompt": "What is the 12345th prime number?",
        "gold": 132241,
    },
]

K = 4  # samples per problem


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Default temperature: pass rate is only meaningful if samples vary. No
# session memory is configured, so the K runs are independent.
teacher = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "Solve the problem step by step. Show your full reasoning, then "
        "give the final integer answer. Do not use any tools; compute by "
        "hand."
    ),
    output_schema=Solution,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "rl_prompts.jsonl"

    rows = []
    dropped_easy = 0
    dropped_hard = 0

    for problem in PROBLEMS:
        correct = 0
        for _ in range(K):
            run: RunOutput = teacher.run(problem["prompt"])
            solution: Solution = run.content
            if solution.final_answer == problem["gold"]:
                correct += 1

        pass_rate = correct / K
        print(
            f"{problem['id']}: {correct}/{K} correct (designed {problem['designed']})"
        )

        if correct == K:
            dropped_easy += 1
        elif correct == 0:
            dropped_hard += 1
        else:
            rows.append(
                {
                    "prompt": problem["prompt"],
                    "gold": problem["gold"],
                    "pass_rate": pass_rate,
                }
            )

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print()
    print("example kept prompt:")
    pprint(rows[0] if rows else None)

    print()
    print(
        f"kept {len(rows)} of {len(PROBLEMS)} prompts (learning zone 0 < pass@{K} < 1)"
    )
    print(
        f"wrote {len(rows)} rows, dropped {dropped_easy} always-solved, "
        f"dropped {dropped_hard} never-solved"
    )
