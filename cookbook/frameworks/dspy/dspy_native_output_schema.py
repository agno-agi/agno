"""
Native structured output with DSPy: type the program's OutputField with a Pydantic
model. DSPy constrains the model to that shape, and the adapter returns the validated
instance directly rather than parsing it out of prose.

Pass output_schema on the run so the framework's typed output is validated end to end.

Requirements:
    pip install dspy

Usage:
    .venvs/demo/bin/python cookbook/frameworks/dspy/dspy_native_output_schema.py
"""

from typing import List

import dspy
from agno.agents.dspy import DSPyAgent
from pydantic import BaseModel, Field


class MovieScript(BaseModel):
    title: str = Field(..., description="Title of the movie")
    genre: str = Field(..., description="Genre of the movie")
    characters: List[str] = Field(..., description="Names of the main characters")


# ----- Configure DSPy LM (must be set on the main thread) -----
lm = dspy.LM("openai/gpt-5.5")
dspy.configure(lm=lm)


# ----- Type the OutputField with the Pydantic model: this is what turns on
#       DSPy's native structured output -----
class WriteScript(dspy.Signature):
    question: str = dspy.InputField()
    answer: MovieScript = dspy.OutputField()


agent = DSPyAgent(name="DSPy Writer", program=dspy.Predict(WriteScript))

response = agent.run("Write a movie script set in Tokyo.", output_schema=MovieScript)

# response.content is a MovieScript instance produced by DSPy, not parsed from text
script = response.content
print("Title:", script.title)
print("Genre:", script.genre)
print("Characters:", ", ".join(script.characters))
