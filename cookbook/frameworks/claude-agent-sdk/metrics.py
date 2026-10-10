"""
Run and session metrics for a ClaudeAgent
=========================================
Every ClaudeAgent run reports the tokens, cache usage and cost that Claude
Code returned for the turn, plus the wall-clock duration measured by Agno,
on RunOutput.metrics. Completed runs are added to the session totals that
AgentOS shows for the session, so Claude sessions appear in the sessions
list and the metrics page like native agents.

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/metrics.py
"""

import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus

SESSION_ID = "metrics-demo"


def show(label: str, metrics) -> None:
    print(f"{label}:")
    print(
        f"  input={metrics.input_tokens} output={metrics.output_tokens} total={metrics.total_tokens}"
    )
    print(
        f"  cache_read={metrics.cache_read_tokens} cache_write={metrics.cache_write_tokens}"
    )
    print(f"  cost=${metrics.cost or 0:.4f} duration={metrics.duration or 0:.2f}s")


def main():
    with tempfile.TemporaryDirectory(prefix="agno-metrics-") as workdir:
        agent = ClaudeAgent(
            id="metrics-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(Path(workdir) / "runs.db")),
            cwd=workdir,
            allowed_tools=["Bash"],
            permission_mode="bypassPermissions",
            max_turns=4,
            max_budget_usd=0.5,
        )

        # 1. A plain turn.
        run = agent.run("Reply with exactly the word OK.", session_id=SESSION_ID)
        assert run.status == RunStatus.completed and run.metrics is not None
        show("Run 1", run.metrics)
        for model in run.metrics.details["model"]:
            print(
                f"  model {model.id}: {model.total_tokens} tokens, ${model.cost or 0:.4f}"
            )

        # 2. A streamed turn with a tool call. The RunCompleted event carries the same metrics.
        completed = None
        for event in agent.run(
            "Run `echo metrics` with Bash and reply with what it printed.",
            session_id=SESSION_ID,
            stream=True,
        ):
            if event.event == "RunCompleted":
                completed = event
        assert completed is not None and completed.metrics is not None
        show("Run 2 (streamed, with a tool call)", completed.metrics)
        print(f"  time_to_first_token={completed.metrics.time_to_first_token:.2f}s")

        # 3. Session totals, as AgentOS reads them from the session.
        session = agent.get_session(SESSION_ID)
        totals = session.session_data["session_metrics"]
        print("Session totals:")
        print(
            f"  total_tokens={totals['total_tokens']} cost=${totals.get('cost', 0):.4f} runs={len(session.runs)}"
        )
        assert (
            totals["total_tokens"]
            == run.metrics.total_tokens + completed.metrics.total_tokens
        )


if __name__ == "__main__":
    main()
