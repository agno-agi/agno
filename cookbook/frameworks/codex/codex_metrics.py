"""
Run and session metrics for a CodexAgent
========================================
Every CodexAgent run reports the token usage Codex returned for the turn,
plus the wall-clock duration measured by Agno, on RunOutput.metrics.
Completed runs are added to the session totals that AgentOS shows for the
session. Codex reports no cost, so cost stays unset.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_metrics.py
"""

import tempfile

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus

SESSION_ID = "codex-metrics-demo"


def show(label: str, metrics) -> None:
    print(f"{label}:")
    print(
        f"  input={metrics.input_tokens} output={metrics.output_tokens} total={metrics.total_tokens}"
    )
    print(
        f"  cached_input={metrics.cache_read_tokens} reasoning={metrics.reasoning_tokens}"
    )
    print(f"  duration={metrics.duration or 0:.2f}s")


def main():
    with tempfile.TemporaryDirectory(prefix="agno-codex-metrics-") as workdir:
        agent = CodexAgent(
            id="codex-metrics",
            model="gpt-5.6-luna",
            sandbox="read-only",
            db=SqliteDb(db_file=f"{workdir}/runs.db"),
            cwd=workdir,
        )

        # 1. A plain turn.
        run = agent.run("Reply with exactly the word OK.", session_id=SESSION_ID)
        assert run.status == RunStatus.completed and run.metrics is not None
        show("Run 1", run.metrics)

        # 2. A streamed turn. The RunCompleted event carries the same metrics.
        completed = None
        for event in agent.run(
            "What is 17 times 3? Reply with just the number.",
            session_id=SESSION_ID,
            stream=True,
        ):
            if event.event == "RunCompleted":
                completed = event
        assert completed is not None and completed.metrics is not None
        show("Run 2 (streamed)", completed.metrics)

        # 3. Session totals, as AgentOS reads them from the session.
        session = agent.get_session(SESSION_ID)
        totals = session.session_data["session_metrics"]
        print("Session totals:")
        print(f"  total_tokens={totals['total_tokens']} runs={len(session.runs)}")
        assert (
            totals["total_tokens"]
            == run.metrics.total_tokens + completed.metrics.total_tokens
        )


if __name__ == "__main__":
    main()
