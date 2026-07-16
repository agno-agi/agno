"""
Workspace — human-in-the-loop confirmation
==========================================

This is the default safety story. Reads run silently; writes/edits/deletes/shell
pause the run and surface a confirmation request. AgentOS renders these as
approval cards in its run timeline. In a plain console, you handle the loop
yourself — that's what this example shows.

Run this in a terminal so you can answer y/n at the prompts.
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.workspace import Workspace
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

console = Console()

workspace = Path(tempfile.mkdtemp(prefix="workspace_hitl_"))
(workspace / "draft.md").write_text(
    "# Draft\n\nThis draft has typos taht need fixing.\n"
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        Workspace(
            str(workspace),
            # Default partition: reads auto-pass, writes need approval.
        )
    ],
    db=SqliteDb(db_file="tmp/workspace_hitl.db"),
    markdown=True,
)


def _drain_pauses(run_response):
    """Approve every pending tool call until the run completes."""
    while run_response.is_paused:
        for requirement in run_response.active_requirements:
            if requirement.needs_confirmation:
                te = requirement.tool_execution
                console.print(
                    f"\n[yellow]Tool[/] [bold blue]{te.tool_name}[/] wants to run with args:\n  {te.tool_args}"
                )
                choice = Prompt.ask("Confirm?", choices=["y", "n"], default="y")
                if choice.strip().lower() == "n":
                    requirement.reject()
                else:
                    requirement.confirm()
        run_response = agent.continue_run(
            run_id=run_response.run_id,
            requirements=run_response.requirements,
        )
    return run_response


if __name__ == "__main__":
    initial = agent.run("Read draft.md and fix the typo on the line about typos.")
    final = _drain_pauses(initial)
    pprint.pprint_run_response(final)
    print(f"\nWorkspace: {workspace}")
    print(f"draft.md after edit:\n{(workspace / 'draft.md').read_text()}")
