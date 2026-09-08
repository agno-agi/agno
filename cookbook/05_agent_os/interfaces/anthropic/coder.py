"""
Coder Agent
============

Reads and edits code locally. Fetches read-only context from GitHub
and the web when needed. Exposed via the Anthropic Messages API so
Claude Code can use it as an upstream model.

Try it from Claude Code:

    export ANTHROPIC_BASE_URL=http://localhost:9001/anthropic
    export ANTHROPIC_AUTH_TOKEN=dev
    export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
    claude
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import LearningMachine
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.os.interfaces.anthropic import AnthropicInterface
from agno.tools.coding import CodingTools
from agno.tools.github import GithubTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Working Directory & Database
# ---------------------------------------------------------------------------
WORKING_DIR = Path(__file__).parent / "tmp" / "anthropicinterface"
WORKING_DIR.mkdir(parents=True, exist_ok=True)

db = SqliteDb(db_file="tmp/anthropic_coder.db")

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are Coder, a local-first coding agent that reads and edits code on
this machine.

## How You Work

1. **Local first.** Your primary workspace is the local filesystem.
   Read files, grep, and edit code directly. Run tests and scripts via
   the shell tool.
2. **Read before editing.** Always read a file before changing it.
   Grep to orient.
3. **Edit surgically.** Use exact text matching. Re-read on failure.
   After 3 edit failures, stop and explain.
4. **Verify.** Run tests after every change. No tests? Suggest them.
5. **Use the web when stuck.** Reach for `WebSearchTools` to look up
   docs, error messages, or APIs you don't recognize.

## GitHub Usage

GitHub access is read-only. Use it to fetch context — pull request
diffs, issue descriptions, comments — not to ship work.

- `get_pull_request`, `get_pull_requests`, `get_pull_request_changes`,
  `get_pull_request_comments` to read PR context.
- `get_issue`, `list_issues` to read issues.

You do NOT create PRs, create issues, comment on issues, or push code.
If the user wants those actions, tell them to do it themselves.

## Constraints

- Never `rm -rf`, `sudo`, or `git reset --hard`.
- Never push code, force-push, or rewrite history.
- NEVER output .env contents, API keys, tokens, passwords, or secrets.

## Communication

- Summarize: what changed, tests passing, remaining work.
- If blocked, explain what you tried and why it failed.\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
coder = Agent(
    id="coder",
    name="Coder",
    role="Read and edit code locally; fetch read-only context from GitHub and the web",
    model=Claude(id="claude-sonnet-4-6"),
    db=db,
    debug_mode=True,
    instructions=instructions,
    learning=LearningMachine(
        user_memory=True,
        session_context=True,
    ),
    tools=[
        CodingTools(base_dir=WORKING_DIR, all=True, shell_timeout=120),
        GithubTools(
            include_tools=[
                "get_pull_request",
                "get_pull_requests",
                "get_pull_request_changes",
                "get_pull_request_comments",
                "get_issue",
                "list_issues",
            ],
        ),
        WebSearchTools(),
        ReasoningTools(),
    ],
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS + Anthropic Interface
# ---------------------------------------------------------------------------
# Set AGNO_ANTHROPIC_INTERFACE_API_KEY in your env to require a static API key
# on every request. Omit it during development to leave the interface open.
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
