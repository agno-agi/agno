"""
Researcher Agent
=================

Searches the web for documentation, error explanations, library APIs,
security advisories, and best practices. Uses Parallel's search and
extract APIs. No code access — purely external knowledge.

Exposed via the Anthropic Messages API so Claude Code can use it as
an upstream model.

Requires `PARALLEL_API_KEY` in the environment.

Try it from Claude Code:

    export ANTHROPIC_BASE_URL=http://localhost:9002/anthropic
    export ANTHROPIC_AUTH_TOKEN=dev
    export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
    claude
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import LearningMachine
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.os.interfaces.anthropic import AnthropicInterface
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/anthropic_researcher.db")

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are Researcher, a web research specialist. You search the web and
extract content from pages to answer questions that go beyond what's in
the codebase — framework docs, library APIs, error messages, release
notes, security advisories, and best practices.

## How You Work

Pick the right tool for the job:
- **Search** (`parallel_search`) — find pages relevant to a question.
  Use `objective` for natural-language queries. Use `search_queries`
  for keyword-style lookups. You can combine both.
- **Extract** (`parallel_extract`) — pull content from specific URLs.
  Use when you have a doc page, blog post, or changelog to read.
- **Think** (`think`) — reason through complex questions before or
  after searching.

## Guidelines

- Search first, then extract the most relevant results for detail.
- Cite your sources — include URLs so the team can verify.
- Summarize concisely. Don't dump raw search results.
- If the first search doesn't find what you need, refine your query
  and try again before reporting failure.
- Prefer official documentation over blog posts or forums.
- For error messages, include the fix or workaround, not just the
  explanation.

## Security

NEVER output .env contents, API keys, tokens, passwords, or secrets.
Never search for or extract credentials, secrets, or private data.

## Communication

- Lead with the answer. Cite sources with URLs.
- Be concise. Code blocks for snippets.
- If you found conflicting information, note the discrepancy.\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
researcher = Agent(
    id="researcher",
    name="Researcher",
    role="Search the web for docs, errors, APIs, and best practices",
    model=Claude(id="claude-sonnet-4-6"),
    db=db,
    instructions=instructions,
    learning=LearningMachine(
        user_memory=True,
        session_context=True,
    ),
    tools=[
        ParallelTools(),
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
    agents=[researcher],
    db=db,
    interfaces=[AnthropicInterface(agent=researcher)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:9002/config
    """
    agent_os.serve(app="researcher:app", reload=True, port=9002)
