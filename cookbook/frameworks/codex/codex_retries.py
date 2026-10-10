"""
Retry failed Codex runs with backoff.

CodexAgent accepts the same retry settings as an Agno Agent. A failed turn
(for example a model error the Codex CLI does not retry itself) is retried
with the same run id. The Codex thread is saved when it starts, so the retry
resumes that thread and Codex sees the work the failed attempt already did.
Cancelled runs are never retried, and a cancel during the backoff wait ends
the run.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_retries.py
"""

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb

# ----- Wrap Codex for Agno with retries -----
agent = CodexAgent(
    name="Codex Assistant",
    model="gpt-5.6-luna",
    sandbox="read-only",
    db=SqliteDb(db_file="tmp/codex_retries.db"),
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
