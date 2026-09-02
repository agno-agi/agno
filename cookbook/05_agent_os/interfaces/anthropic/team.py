"""
Multi-Agent Anthropic Interface
================================

Exposes three runners through a single `AnthropicInterface`, each
advertised as its own Claude Code model:

- `claude-agno-coder`            -> coder agent (from `coder.py`)
- `claude-agno-researcher`       -> researcher agent (from `researcher.py`)
- `claude-agno-coder-researcher-team` -> team leader that routes between them

Endpoints are mounted under `/anthropic/v1/...`.

Try it from Claude Code:

    export ANTHROPIC_BASE_URL=http://localhost:9001/anthropic
    export ANTHROPIC_AUTH_TOKEN=dev
    export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
    claude

Then pick a model in Claude Code's selector to switch between the
coder, researcher, and the team.
"""

from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.os.interfaces.anthropic import AnthropicInterface
from agno.team import Team

from coder import coder
from researcher import researcher

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/anthropic_multi.db")

# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
instructions = """\
You lead a team with two specialists:

- **Coder** — reads and edits code locally. Use for any task that
  involves the local filesystem, running tests, or making changes to
  code. Coder can also fetch read-only context from GitHub.
- **Researcher** — searches the web and extracts content from pages.
  Use for framework docs, library APIs, error messages, release notes,
  security advisories, and best practices.

## How to Route

- Code changes, file edits, test runs -> Coder.
- Questions about external libraries, errors, or docs -> Researcher.
- Mixed work: hand off to Researcher first for context, then Coder to
  apply the fix.

Be explicit about which agent you are delegating to and why.

NEVER output .env contents, API keys, tokens, passwords, or secrets.\
"""

team = Team(
    id="coder-researcher-team",
    name="CoderResearcherTeam",
    model=Claude(id="claude-sonnet-4-6"),
    members=[coder, researcher],
    instructions=instructions,
    db=db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS + Anthropic Interface (multi-model)
# ---------------------------------------------------------------------------
# Set AGNO_ANTHROPIC_INTERFACE_API_KEY in your env to require a static API key
# on every request. Omit it during development to leave the interface open.
agent_os = AgentOS(
    agents=[coder, researcher],
    teams=[team],
    db=db,
    interfaces=[
        AnthropicInterface(
            agents=[coder, researcher],
            teams=[team],
        ),
    ],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:9001/config

    Anthropic-compatible endpoints:
    - POST http://localhost:9001/anthropic/v1/messages
    - GET  http://localhost:9001/anthropic/v1/models
    """
    agent_os.serve(app="team:app", reload=True, port=9001)
