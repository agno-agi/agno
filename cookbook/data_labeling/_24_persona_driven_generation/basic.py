"""
Persona-Driven Generation - Basic
=================================

PersonaHub-style prompt generation: a persona agent invents a small cast of
typed personas (occupation, expertise level, communication style, current
concern), then a prompt agent asks, for each persona, what that person would
actually want to know about a fixed domain. The persona travels with every
row as provenance, so downstream curation can trace which voice produced
which prompt.
"""

import json
from pathlib import Path
from typing import Literal

from agno.agent import Agent, RunOutput
from pydantic import BaseModel, Field
from rich.pretty import pprint

DOMAIN = "personal finance"
PERSONA_COUNT = 6
PROMPTS_PER_PERSONA = 2


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Persona(BaseModel):
    occupation: str = Field(
        ..., description="The persona's job or role, specific enough to imply a world"
    )
    expertise_level: Literal["novice", "intermediate", "expert"] = Field(
        ..., description="How much the persona already knows about the domain"
    )
    communication_style: str = Field(
        ...,
        description="How the persona talks, e.g. 'plainspoken and practical' or 'terse and technical'",
    )
    current_concern: str = Field(
        ...,
        description="The concrete problem on the persona's mind right now, tied to their occupation",
    )


class Personas(BaseModel):
    personas: list[Persona] = Field(
        ...,
        description="Distinct personas that differ in occupation, expertise level, style, and concern",
    )


class Prompts(BaseModel):
    prompts: list[str] = Field(
        ...,
        description="Self-contained questions this persona would plausibly ask, written in the persona's own voice",
    )


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
persona_agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You invent personas for synthetic data generation. Make them "
        "concrete and mutually distinct: no two personas may share an "
        "occupation, and the set must span all three expertise levels. "
        "Each current_concern must be specific to that occupation, not a "
        "generic worry."
    ),
    output_schema=Personas,
)

prompt_agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You write questions on behalf of a persona. Given a persona and a "
        "domain, write questions that THIS person would actually ask about "
        "the domain: grounded in their occupation and current concern, "
        "phrased in their communication style, and pitched at their "
        "expertise level. Each question must be self-contained."
    ),
    output_schema=Prompts,
)


# ---------------------------------------------------------------------------
# Run Generation
# ---------------------------------------------------------------------------
def build_prompt_request(persona: Persona) -> str:
    lines = [
        "Persona:",
        f"- occupation: {persona.occupation}",
        f"- expertise_level: {persona.expertise_level}",
        f"- communication_style: {persona.communication_style}",
        f"- current_concern: {persona.current_concern}",
        "",
        f"Write {PROMPTS_PER_PERSONA} questions this persona would ask about {DOMAIN}.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "persona_prompts.jsonl"

    persona_run: RunOutput = persona_agent.run(
        f"Invent {PERSONA_COUNT} personas who might have questions about {DOMAIN}."
    )
    personas = persona_run.content.personas[:PERSONA_COUNT]

    rows = []
    for persona in personas:
        prompt_run: RunOutput = prompt_agent.run(build_prompt_request(persona))
        for prompt in prompt_run.content.prompts[:PROMPTS_PER_PERSONA]:
            rows.append({"prompt": prompt.strip(), "persona": persona.model_dump()})

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    pprint(rows[:3])
    print(
        f"wrote {len(rows)} rows to {out_path} "
        f"({len(personas)} personas x {PROMPTS_PER_PERSONA} prompts each)"
    )
