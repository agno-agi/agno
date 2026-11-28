"""Inspect Prime's native tool calls through Agno streaming events."""

from os import getenv
from pathlib import Path

from agno.agents.prime import PrimeAgent
from agno.run.agent import RunContentEvent, RunOutput, ToolCallCompletedEvent
from agno.run.base import RunStatus

agent = PrimeAgent(
    name="Prime Reviewer",
    cwd=getenv(
        "PRIME_AGENT_CWD", str(Path(__file__).resolve().parents[1] / "sample_project")
    ),
    instructions="Read the project to answer. Ask before modifying files.",
)

if __name__ == "__main__":
    for event in agent.run(
        "Read shipping.py and explain the shipping policy with examples.",
        stream=True,
        yield_run_output=True,
    ):
        if isinstance(event, RunContentEvent):
            print(event.content or "", end="", flush=True)
        elif isinstance(event, ToolCallCompletedEvent) and event.tool:
            print(
                f"\nTool: {event.tool.tool_name} | Error: {event.tool.tool_call_error}"
            )
        elif isinstance(event, RunOutput) and event.status != RunStatus.completed:
            raise RuntimeError(str(event.content))
    print()
