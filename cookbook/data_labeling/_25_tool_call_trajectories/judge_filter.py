"""
Tool Call Trajectories - Judge Filter
=====================================

Keep only tool-use trajectories a judge verifies. This file re-runs the
multi-turn simulation from multi_turn_simulation.py (imported, so it runs
standalone without any pre-existing JSONL), then a temperature-0 judge
reads each conversation plus the tool calls the assistant actually
executed and decides whether the user's goal was accomplished. Successful
rollouts are exported with the judge's reason in provenance; failures are
dropped with printed reasons.
"""

import json
from pathlib import Path

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from multi_turn_simulation import PERSONAS, render_transcript, run_conversation
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class TrajectoryVerdict(BaseModel):
    success: bool = Field(
        ...,
        description="True only if every step of the user's goal was answered correctly using the executed tool calls",
    )
    reason: str = Field(
        ...,
        description="One or two sentences citing the specific tool calls or answers behind the verdict",
    )


# ---------------------------------------------------------------------------
# Create Judge Agent
# ---------------------------------------------------------------------------
judge = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=(
        "You audit tool-use trajectories. Given a user goal, a conversation, "
        "and the tool calls the assistant actually executed, verify that the "
        "assistant accomplished every step of the goal with correct tool "
        "arguments and correct arithmetic. Wrong numbers, skipped steps, or "
        "final answers not backed by an executed tool call mean failure."
    ),
    output_schema=TrajectoryVerdict,
)


def build_judge_prompt(row: dict) -> str:
    return (
        f"User goal (persona '{row['persona']}'):\n{PERSONAS[row['persona']]}\n\n"
        f"Conversation:\n{render_transcript(row['messages'])}\n\n"
        f"Executed tool calls:\n{json.dumps(row['tool_calls'], indent=2)}\n\n"
        "Did the assistant accomplish every step of the goal?"
    )


# ---------------------------------------------------------------------------
# Run Judge Filter
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "verified_trajectories.jsonl"

    kept_rows = []
    dropped = 0
    for persona in PERSONAS:
        row = run_conversation(persona)
        print(
            f"{persona}: {row['turns']} turns, {len(row['tool_calls'])} executed tool calls"
        )
        run: RunOutput = judge.run(build_judge_prompt(row))
        verdict: TrajectoryVerdict = run.content
        if verdict.success:
            row["provenance"] = {"judge": "gemini-3.5-flash", "reason": verdict.reason}
            kept_rows.append(row)
            print(f"kept {persona}: {verdict.reason}")
        else:
            dropped += 1
            print(f"dropped {persona}: {verdict.reason}")

    with out_path.open("w") as f:
        for row in kept_rows:
            f.write(json.dumps(row) + "\n")

    kept = len(kept_rows)
    print(f"wrote {kept} rows to {out_path}, kept {kept}, dropped {dropped}")
