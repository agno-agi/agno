"""
Structured output next to tool calls.

Claude Code delivers an output_schema object through an internal tool call named
StructuredOutput. The adapter reads the object from the result message and does not
record that call as a tool, so run.tools, the tool events and the stored history hold
only the tools the agent used. The schema must describe a JSON object: an array or
scalar at the top level is refused before the run instead of failing on the API.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/structured_output_tools.py
"""

import tempfile
from typing import List

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.run.agent import RunCompletedEvent, ToolCallCompletedEvent
from pydantic import BaseModel, Field, RootModel


class DiskUsage(BaseModel):
    directory: str = Field(..., description="The directory that was measured")
    size: str = Field(..., description="Size as reported by du, for example 12K")


class Names(RootModel[List[str]]):
    """A list at the top level: not an object, so it cannot be an output_schema."""


workdir = tempfile.mkdtemp(prefix="agno-structured-tools-")
agent = ClaudeAgent(
    name="Claude Disk Checker",
    model="claude-sonnet-4-6",
    cwd=workdir,
    db=SqliteDb(db_file=f"{workdir}/runs.db"),
    system_prompt=f"You work in {workdir}. Use Bash for measurements.",
    allowed_tools=["Bash"],
    permission_mode="bypassPermissions",
    max_turns=4,
    output_schema=DiskUsage,
)
prompt = "Measure the size of the current directory with `du -sh .` and report it."

# ----- Non-streaming: only the Bash call is recorded -----
run = agent.run(prompt, session_id="disk")
print("content:", run.content, "| content_type:", run.content_type)
print("tools:", [(tool.tool_name, tool.tool_args) for tool in run.tools or []])
print(
    "tool results in history:",
    [message.content for message in run.messages or [] if message.role == "tool"],
)
assert [tool.tool_name for tool in run.tools or []] == ["Bash"]

# ----- Streaming: tool events for Bash only, the object on RunCompleted -----
completed_tools = []
for event in agent.run(prompt, session_id="disk", stream=True):
    if isinstance(event, ToolCallCompletedEvent):
        completed_tools.append(event.tool.tool_name)
    elif isinstance(event, RunCompletedEvent):
        print("RunCompleted:", event.content, "| content_type:", event.content_type)
print("tool events:", completed_tools)
assert completed_tools == ["Bash"]

# ----- A schema that is not an object is refused before the run -----
try:
    agent.run("List three colours.", session_id="colours", output_schema=Names)
except ValueError as error:
    print("refused:", error)
