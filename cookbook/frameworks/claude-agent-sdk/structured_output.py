"""
Claude Agent SDK with structured output.

Pass a Pydantic model as `output_schema` and the run content is an instance of
that model, as with a native Agno Agent. A plain JSON Schema dict returns a dict.
The schema can also be passed per run, overriding the agent's.

Claude Code delivers the object through a StructuredOutput tool call and then
replies in prose, so the streamed text is the reply and the RunCompleted event
carries the parsed object.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/structured_output.py
"""

from typing import List

from agno.agents.claude import ClaudeAgent
from agno.run.agent import RunCompletedEvent, RunOutput
from pydantic import BaseModel, Field


# ----- Output schema -----
class FileSummary(BaseModel):
    path: str = Field(
        ..., description="Path of the file, relative to the working directory"
    )
    purpose: str = Field(..., description="One sentence on what the file does")


class ProjectSummary(BaseModel):
    language: str = Field(..., description="Main programming language")
    files: List[FileSummary] = Field(
        ..., description="Up to three of the most important files"
    )


agent = ClaudeAgent(
    name="Claude Project Summarizer",
    model="claude-sonnet-5-5",
    allowed_tools=["Read", "Glob"],
    output_schema=ProjectSummary,
)

prompt = "Look at the Python files in cookbook/frameworks/claude-agent-sdk and summarize them."

# ----- Non-streaming: content is a ProjectSummary -----
run_output = agent.run(prompt)
assert isinstance(run_output, RunOutput)
assert isinstance(run_output.content, ProjectSummary)
print("content_type:", run_output.content_type)
print(run_output.content.model_dump_json(indent=2))

# ----- Streaming: text deltas are the reply, RunCompleted carries the object -----
for event in agent.run(prompt, stream=True):
    if isinstance(event, RunCompletedEvent):
        print("\nRunCompleted content_type:", event.content_type)
        print(event.content)

# ----- Per-run JSON Schema: content is a dict -----
count_schema = {
    "type": "object",
    "properties": {"python_files": {"type": "integer"}},
    "required": ["python_files"],
}
counted = agent.run(
    "How many .py files are directly inside cookbook/frameworks/claude-agent-sdk?",
    output_schema=count_schema,
)
assert isinstance(counted, RunOutput)
print("\nPer-run schema:", counted.content_type, counted.content)
