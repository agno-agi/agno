"""
Instruction Generation - Evol-Instruct
======================================

Grow instruction complexity through typed evolution operators. Each seed is
evolved twice in a chain (seed -> depth 1 -> depth 2); the operator for each
call is chosen by deterministic round-robin so all five operators appear
across the run. A stdlib eliminator drops no-op evolutions (near-identical
to the parent) and degenerate ones (too short), so every kept row is a real
transformation with recorded provenance: parent, operator, depth.
"""

import json
from pathlib import Path
from typing import Literal

from agno.agent import Agent, RunOutput
from pydantic import BaseModel, Field
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Seeds and Operators
# ---------------------------------------------------------------------------
SEEDS = [
    "Write a short story about a lighthouse keeper.",
    "Explain how a hash table works.",
    "Summarize the causes of the French Revolution.",
    "Write a Python function that checks if a string is a palindrome.",
    "Give tips for improving sleep quality.",
]

Operator = Literal[
    "add_constraints", "deepen", "concretize", "increase_reasoning", "in_breadth"
]

OPERATORS: list[Operator] = [
    "add_constraints",
    "deepen",
    "concretize",
    "increase_reasoning",
    "in_breadth",
]

OPERATOR_PROMPTS = {
    "add_constraints": (
        "Add one or two concrete constraints or requirements to the "
        "instruction (length limits, required format, forbidden approaches, "
        "specific inputs). Keep the original task recognizable."
    ),
    "deepen": (
        "Increase the depth of the instruction: require more detail, more "
        "edge cases, or a more thorough treatment of the same task."
    ),
    "concretize": (
        "Replace abstract or general terms in the instruction with concrete, "
        "specific ones (a named scenario, real quantities, a specific "
        "audience or dataset)."
    ),
    "increase_reasoning": (
        "Rewrite the instruction so answering it requires explicit "
        "multi-step reasoning, not just recall. Ask for the steps to be "
        "shown."
    ),
    "in_breadth": (
        "Write a brand-new instruction in the same domain as the given one, "
        "but on a different, rarer topic of similar difficulty. Do not "
        "reuse the original task."
    ),
}

STEPS_PER_SEED = 2
MIN_WORDS = 4
NOOP_JACCARD = 0.85


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class EvolvedInstruction(BaseModel):
    instruction: str = Field(
        ...,
        description="The evolved instruction, self-contained and answerable on its own",
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
evolver = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You evolve training instructions for a language model. Apply the "
        "requested evolution operator to the given instruction and return "
        "only the evolved instruction. It must remain self-contained and "
        "answerable without external files or links."
    ),
    output_schema=EvolvedInstruction,
)


# ---------------------------------------------------------------------------
# Eliminator (stdlib)
# ---------------------------------------------------------------------------
def word_set(text: str) -> set:
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower())
    return set(cleaned.split())


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def eliminate(evolved: str, parent: str) -> str:
    if len(evolved.split()) < MIN_WORDS:
        return "degenerate"
    if jaccard(word_set(evolved), word_set(parent)) > NOOP_JACCARD:
        return "no-op"
    return ""


# ---------------------------------------------------------------------------
# Run Evolution
# ---------------------------------------------------------------------------
def build_prompt(operator: Operator, instruction: str) -> str:
    return f"Operator: {OPERATOR_PROMPTS[operator]}\n\nInstruction:\n{instruction}"


if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "evolved_instructions.jsonl"

    rows = []
    dropped = 0
    call_idx = 0

    for seed in SEEDS:
        current = seed
        depth = 0
        for _ in range(STEPS_PER_SEED):
            operator = OPERATORS[call_idx % len(OPERATORS)]
            call_idx += 1

            run: RunOutput = evolver.run(build_prompt(operator, current))
            evolved = run.content.instruction.strip()

            reason = eliminate(evolved, current)
            if reason:
                dropped += 1
                continue

            depth += 1
            rows.append(
                {
                    "instruction": evolved,
                    "parent": current,
                    "operator": operator,
                    "depth": depth,
                }
            )
            current = evolved

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    pprint(rows[:2])
    kept = len(rows)
    print(
        f"wrote {kept} rows to {out_path} from {call_idx} evolution calls, kept {kept}, dropped {dropped}"
    )
