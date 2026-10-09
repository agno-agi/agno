"""
Codex with structured output.

Pass a JSON Schema as `output_schema` and Codex constrains its final answer
to that schema. The run content is the JSON string, ready for json.loads().

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_structured_output.py
"""

import json

from agno.agents.codex import CodexAgent
from agno.run.agent import RunOutput

# ----- JSON Schema for the final answer -----
movie_schema = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "year": {"type": "integer"},
        "genres": {"type": "array", "items": {"type": "string"}},
        "one_line_pitch": {"type": "string"},
    },
    "required": ["title", "year", "genres", "one_line_pitch"],
    "additionalProperties": False,
}

agent = CodexAgent(
    name="Codex Movie Writer",
    model="gpt-5.6-luna",
    sandbox="read-only",
    output_schema=movie_schema,
)

run_output = agent.run("Invent a science fiction movie set on Mars.")
assert isinstance(run_output, RunOutput)

movie = json.loads(str(run_output.content))
print(json.dumps(movie, indent=2))
