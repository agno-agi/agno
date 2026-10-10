"""
Retry failed Codex runs
=======================
CodexAgent takes the same retry settings as an Agno Agent: retries,
delay_between_retries and exponential_backoff. A failed attempt is retried
with the same run id, and because the Codex thread id is saved when the
thread starts, the retry resumes that thread rather than starting over.

Errors that would fail the same way again are not retried: session budget
and usage limits, context window overflows, authentication, bad requests and
policy blocks. Cancelled runs are never retried.

This cookbook makes the failure happen on purpose. The first attempt is cut
off with a simulated transient error at the end of the turn, so you can
watch the retry resume the same thread and finish. The failure stands in for
a model or connection error that the Codex CLI does not retry itself.

Two of the four cases are meant to end in a failed run, and a run that ends
in ERROR is logged with its traceback. Those ERROR lines are the expected
result of the case printed just before them.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_retries.py
"""

import tempfile

from openai_codex.api import AsyncTurnHandle

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus

outage = {"remaining": 0, "attempts": 0, "threads": []}
_stream = AsyncTurnHandle.stream


async def stream_with_outage(self):
    """Yield the turn's notifications, but fail the attempt at its end when an outage is pending."""
    outage["attempts"] += 1
    outage["threads"].append(self.thread_id)
    async for notification in _stream(self):
        if (
            outage["remaining"] > 0
            and getattr(notification, "method", "") == "turn/completed"
        ):
            outage["remaining"] -= 1
            raise RuntimeError("simulated transient failure")
        yield notification


AsyncTurnHandle.stream = stream_with_outage


def simulate_outages(count: int) -> None:
    outage.update(remaining=count, attempts=0, threads=[])


def main():
    with tempfile.TemporaryDirectory(prefix="agno-codex-retries-") as workdir:
        db = SqliteDb(db_file=f"{workdir}/runs.db")
        agent = CodexAgent(
            id="retries-demo",
            model="gpt-5.6-luna",
            sandbox="read-only",
            db=db,
            cwd=workdir,
            # Retry up to 2 times, waiting 1s then 2s
            retries=2,
            delay_between_retries=1,
            exponential_backoff=True,
        )

        # 1. One transient failure, then success. Watch the warning line from the retry.
        print(
            "Case 1: one transient failure, then success. One retry warning is expected:"
        )
        simulate_outages(1)
        run = agent.run(
            "What is 17 times 3? Reply with just the number.", session_id="retry"
        )
        print(
            f"Attempts: {outage['attempts']}, status: {run.status}, answer: {run.content!r}"
        )
        print(
            f"Codex thread per attempt: {[thread[:8] for thread in outage['threads']]}"
        )
        assert run.status == RunStatus.completed and outage["attempts"] == 2
        assert len(set(outage["threads"])) == 1, (
            "the retry resumed the thread the failed attempt started"
        )

        # 2. Streaming retries the same way; the RunCompleted event closes the stream.
        print("\nCase 2: the same with streaming. One retry warning is expected:")
        simulate_outages(1)
        events = list(
            agent.run(
                "Name three primary colors, comma separated.",
                session_id="retry",
                stream=True,
            )
        )
        print(
            f"Streamed: attempts: {outage['attempts']}, last event: {events[-1].event}, answer: {events[-1].content!r}"
        )
        assert events[-1].event == "RunCompleted" and outage["attempts"] == 2

        # 3. More failures than retries: the run ends with the last error.
        print(
            "\nCase 3: more failures than retries. Two retry warnings and one ERROR are expected:"
        )
        simulate_outages(5)
        run = agent.run("Reply with exactly OK.", session_id="exhausted")
        print(
            f"Attempts: {outage['attempts']}, status: {run.status}, error: {run.content!r}"
        )
        assert run.status == RunStatus.error and outage["attempts"] == 3

        # 4. The default is no retries.
        print("\nCase 4: retries=0, the default. One ERROR and no retry are expected:")
        simulate_outages(1)
        plain = CodexAgent(
            id="plain-demo",
            model="gpt-5.6-luna",
            sandbox="read-only",
            db=db,
            cwd=workdir,
        )
        run = plain.run("Reply with exactly OK.", session_id="plain")
        print(
            f"retries=0 (default): attempts: {outage['attempts']}, status: {run.status}"
        )
        assert run.status == RunStatus.error and outage["attempts"] == 1


if __name__ == "__main__":
    main()
