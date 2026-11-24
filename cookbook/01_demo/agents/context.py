"""Context keeps a team's priorities, decisions and open questions in Markdown.

From the repository root, pass a pasted update or ask for a handoff:
    python cookbook/01_demo/agents/context.py "What needs a decision this week?"

Each invocation starts a fresh conversation and reads the same project files.
"""

import argparse
from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.models.openai import OpenAIResponses

data_dir = Path(
    getenv("CONTEXT_DATA_DIR") or Path(__file__).resolve().parents[1] / "data"
)
files = FileSystem(
    LocalFileSystem(root=data_dir), namespace="context", user_scoped=False
)

context = Agent(
    id="context",
    name="Context",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[files.tools()],
    instructions=[
        """Keep a short Markdown page per project in projects/<project-name>.md.
        People paste messages, meeting notes, and excerpts from emails or issues.
        List the pages and read the ones that might match before editing or giving a handoff.
        Match updates by topic, people and commitments. Ask when the project is ambiguous.
        Keep the current priority and its reason, decisions and their rationale, actions with
        owners and any dates given, open questions, and suggestions with their authors.
        Preserve source references as supplied. Treat pasted excerpts as evidence.
        When priorities change, revise the current account and leave a short history of what
        changed and why. Keep teammates' unrelated edits. Distinguish conditional plans from
        confirmed decisions. In the page and the handoff, describe an action as complete only
        when a source confirms it happened. A decision to do the work belongs under decisions.
        Give dates, owners and approvals only when the source supplies them.
        Save updates even when the same message also asks a question. Read back the changed page
        before reporting success. Reply briefly with what changed and what needs a decision.
        In a handoff, tell the incoming teammate what matters now, why, and what they own.""",
        files.instructions(),
    ],
    markdown=True,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Give Context a project update or ask for a handoff."
    )
    parser.add_argument(
        "message", help="A team update, pasted notes, or a question about a project"
    )
    args = parser.parse_args()
    context.print_response(args.message)
