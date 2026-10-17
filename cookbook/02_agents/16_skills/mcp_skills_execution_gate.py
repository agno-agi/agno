"""
MCP Skills Execution Gate
=============================

Skills from an MCP server are written by that server, so they can tell the model
to run code with the agent's other tools. Once a run loads an MCP-served skill,
agno's code-execution tools (ShellTools, PythonTools, ...) require confirmation
for the rest of that run.

Here the agent loads Hugging Face's `hf-cli` skill, which recommends running `hf`
commands, and every shell call it then makes pauses for your approval. Add your
own execution tools with `MCPSkills(..., gated_tools=[...])`, or gate every tool
with `gate_all_tools=True`.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.skills import MCPSkills, Skills
from agno.tools.shell import ShellTools
from rich.console import Console
from rich.prompt import Prompt

console = Console()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
huggingface_skills = MCPSkills(url="https://huggingface.co/mcp", label="hf")

agent = Agent(
    name="Hugging Face Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[ShellTools()],
    skills=Skills(loaders=[huggingface_skills]),
    instructions=[
        "Use the hf/hf-cli skill, then run the command it recommends with the shell."
    ],
    db=SqliteDb(db_file="tmp/mcp_skills.db"),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    run = await agent.arun("Which version of the Hugging Face hf CLI is installed?")

    # The gate stays on for the rest of the run, so every shell call pauses.
    while run.is_paused:
        for requirement in run.active_requirements:
            if requirement.needs_confirmation:
                tool = requirement.tool_execution
                console.print(
                    f"Tool [bold blue]{tool.tool_name}({tool.tool_args})[/] requires confirmation."
                )
                answer = Prompt.ask("Run it?", choices=["y", "n"], default="n")
                if answer == "y":
                    requirement.confirm()
                else:
                    requirement.reject()
        run = await agent.acontinue_run(
            run_id=run.run_id, requirements=run.requirements
        )

    console.print(run.content)


if __name__ == "__main__":
    asyncio.run(main())
