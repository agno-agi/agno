"""
Codex with structured output.

Pass a Pydantic model as `output_schema` and the run content is an instance of
that model, as with a native Agno Agent. The model is sent to Codex as a strict
JSON Schema (no extra keys, every field required). A plain JSON Schema dict is
sent as given and returns a dict. The schema can also be passed per run.

When streaming, the text deltas include Codex's commentary before the answer;
the RunCompleted event carries the parsed final answer.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_structured_output.py
"""

from typing import List

from agno.agents.codex import CodexAgent
from agno.run.agent import RunOutput
from pydantic import BaseModel, Field


# ----- Output schema -----
class Movie(BaseModel):
    title: str
    year: int
    genres: List[str]
    one_line_pitch: str = Field(..., description="A single sentence selling the movie")


agent = CodexAgent(
    name="Codex Movie Writer",
    model="gpt-5.6-luna",
    sandbox_mode="read-only",
    output_schema=Movie,
)

# ----- Streaming: the printer returns the parsed final answer -----
run_output = agent.print_response(
    "Invent a science fiction movie set on Mars.", stream=True
)
assert isinstance(run_output, RunOutput)
assert isinstance(run_output.content, Movie)
print("content_type:", run_output.content_type)
print(run_output.content.model_dump_json(indent=2))

# ----- Per-run JSON Schema: content is a dict -----
title_schema = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}
titled = agent.print_response(
    "Suggest a title for a documentary about bees.",
    output_schema=title_schema,
    stream=True,
)
assert isinstance(titled, RunOutput)
print("\nPer-run schema:", titled.content_type, titled.content)
