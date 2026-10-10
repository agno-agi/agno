"""
Retry failed Claude Agent SDK runs with backoff.

ClaudeAgent accepts the same retry settings as an Agno Agent. A failed run
(for example an API error that outlasts the Claude Code CLI's own retries) is
retried with the same run id. Because the SDK session id is saved as soon as
the run starts, the retry resumes that session, so Claude sees the work the
failed attempt already did.

Errors that would fail the same way again are not retried: max_turns and
max_budget_usd limits (a retry would grant a fresh allowance), authentication
and billing errors, and invalid requests. Cancelled runs are never retried,
and a cancel during the backoff wait ends the run.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/claude_retries.py
"""

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb

# ----- Wrap Claude Agent SDK for Agno with retries -----
agent = ClaudeAgent(
    name="Claude Assistant",
    model="claude-sonnet-4-6",
    max_turns=3,
    db=SqliteDb(db_file="tmp/claude_retries.db"),
    # Retry up to 3 times, waiting 2s, 4s, then 8s
    retries=3,
    delay_between_retries=2,
    exponential_backoff=True,
)

agent.print_response(
    "What is quantum computing? Explain in 2-3 sentences.",
    stream=True,
    session_id="retries-demo",
)
