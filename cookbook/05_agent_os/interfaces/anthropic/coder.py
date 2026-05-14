"""
Coder
=====

A mini clone of agno-agi/coda's Coder agent.

This agent writes, reads, and edits local files inside a sandboxed workspace
directory (`tmp/coder_workspace/`). Sessions and history are persisted to a
local SQLite database so the agent can resume across runs.

The agent is exposed behind the Anthropic Messages API via `AnthropicInterface`,
so the Anthropic Python SDK (or Claude Code with
`ANTHROPIC_BASE_URL=http://localhost:9001`) can drive it.

Try it with the Anthropic SDK:

    import anthropic
    client = anthropic.Anthropic(api_key="dev", base_url="http://localhost:9001")
    msg = client.messages.create(
        model="claude-agno-coder",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Create hello.py that prints Hello, Coder."}],
    )
    print(msg.content[0].text)
"""

from pathlib import Path

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.anthropic import AnthropicInterface
from agno.tools.file import FileTools
from agno.tools.reasoning import ReasoningTools

# ---------------------------------------------------------------------------
# Workspace and Storage
# ---------------------------------------------------------------------------

WORKSPACE = Path("tmp/coder_workspace").resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

db = SqliteDb(db_file="tmp/coder.db")

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

instructions = f"""\
You are Coder, a coding agent that writes, reads, and edits local files.

## Workspace

All your file operations are sandboxed to `{WORKSPACE}`. You cannot read or
write outside this directory. Use relative paths.

## How You Work

1. Read first. Always read before editing. Use list_files and search_content
   to orient yourself.
2. Edit surgically. Prefer replace_file_chunk over rewriting whole files.
   Re-read on failure. After 3 edit failures, stop and explain.
3. Verify. After saving a file, read it back to confirm the contents.
4. Summarize at the end: what changed, which files, anything left to do.

## Constraints

- Never operate outside the workspace directory.
- Never output secrets, API keys, tokens, or passwords.
- If a request is ambiguous, ask one clarifying question before acting.
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

coder = Agent(
    id="coder",
    name="Coder",
    role="Write, read, and edit local files in a sandboxed workspace",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    instructions=instructions,
    tools=[
        FileTools(base_dir=WORKSPACE, all=True),
        ReasoningTools(),
    ],
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[coder],
    db=db,
    interfaces=[AnthropicInterface(agent=coder)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:9001/config
    """
    agent_os.serve(app="coder:app", reload=True, port=9001)
