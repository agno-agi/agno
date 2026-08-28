"""
Structured output with a DSPy program, using a Pydantic schema.

The schema can be set on the agent, or passed per-run to override it.

Requirements:
    uv pip install dspy

Usage:
    .venvs/demo/bin/python cookbook/frameworks/dspy/dspy_output_schema.py
"""

from typing import List

import dspy
from agno.agents.dspy import DSPyAgent
from pydantic import BaseModel, Field


class MovieScript(BaseModel):
    title: str = Field(..., description="Title of the movie")
    genre: str = Field(..., description="Genre of the movie")
    characters: List[str] = Field(..., description="Names of the main characters")
    plot: str = Field(..., description="One paragraph plot summary")


class Haiku(BaseModel):
    lines: List[str] = Field(..., description="The three lines of the haiku")


# ----- Configure DSPy LM -----
lm = dspy.LM("openai/gpt-5.5")
dspy.configure(lm=lm)

# ----- Schema set on the agent -----
agent = DSPyAgent(
    name="DSPy Writer",
    program=dspy.Predict("question -> answer"),
    output_schema=MovieScript,
)

response = agent.run("Write a movie script set in Tokyo.")

# response.content is a MovieScript instance
script = response.content
print("Title:", script.title)
print("Genre:", script.genre)
print("Characters:", ", ".join(script.characters))
print("Plot:", script.plot)

# ----- Per-run schema overrides the agent-level one -----
response = agent.run("Write a haiku about Tokyo.", output_schema=Haiku)

haiku = response.content
print()
for line in haiku.lines:
    print(line)
