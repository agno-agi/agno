"""
Retry failed Claude Agent SDK runs
==================================
ClaudeAgent takes the same retry settings as an Agno Agent: retries,
delay_between_retries and exponential_backoff. A failed attempt is retried
with the same run id, and because the SDK session id is saved as soon as the
session starts, the retry resumes that session rather than starting over.

Errors that would fail the same way again are not retried: max_turns and
max_budget_usd limits (a retry would grant a fresh allowance), authentication
and billing errors, and invalid requests. Cancelled runs are never retried.

This cookbook makes the failure happen on purpose. The first attempt is cut
off with a simulated transient error after Claude has already answered, so
you can watch the retry resume the same session and finish. Nothing about
the failure is special to Agno; it stands in for a network drop or an API
error that outlasts the CLI's own retries.

Three of the four cases are meant to end in a failed run, and a run that ends
in ERROR is logged with its traceback. Those ERROR lines are the expected
result of the case printed just before them.

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/claude_retries.py
"""

import tempfile
from pathlib import Path

import claude_agent_sdk as sdk

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus

outage = {"remaining": 0, "attempts": 0, "session_ids": []}
_receive_response = sdk.ClaudeSDKClient.receive_response


async def receive_with_outage(self):
    """Yield the SDK's messages, but fail the attempt at its result when an outage is pending."""
    outage["attempts"] += 1
    async for message in _receive_response(self):
        if isinstance(message, sdk.SystemMessage) and message.subtype == "init":
            outage["session_ids"].append(message.data.get("session_id"))
        if outage["remaining"] > 0 and isinstance(message, sdk.ResultMessage):
            outage["remaining"] -= 1
            raise RuntimeError("simulated transient failure")
        yield message


sdk.ClaudeSDKClient.receive_response = receive_with_outage


def simulate_outages(count: int) -> None:
    outage.update(remaining=count, attempts=0, session_ids=[])


def main():
    with tempfile.TemporaryDirectory(prefix="agno-retries-") as workdir:
        db = SqliteDb(db_file=str(Path(workdir) / "runs.db"))
        agent = ClaudeAgent(
            id="retries-demo",
            model="claude-sonnet-4-6",
            db=db,
            cwd=workdir,
            allowed_tools=["Bash"],
            permission_mode="bypassPermissions",
            max_turns=4,
            max_budget_usd=0.5,
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
            "Run `echo hello` with Bash and reply with what it printed.",
            session_id="retry",
        )
        print(
            f"Attempts: {outage['attempts']}, status: {run.status}, answer: {run.content!r}"
        )
        print(f"SDK session per attempt: {outage['session_ids']}")
        assert run.status == RunStatus.completed and outage["attempts"] == 2
        assert len(set(outage["session_ids"])) == 1, (
            "the retry resumed the session the failed attempt started"
        )

        # 2. More failures than retries: the run ends with the last error.
        print(
            "\nCase 2: more failures than retries. Two retry warnings and one ERROR are expected:"
        )
        simulate_outages(5)
        run = agent.run("Reply with exactly OK.", session_id="exhausted")
        print(
            f"Attempts: {outage['attempts']}, status: {run.status}, error: {run.content!r}"
        )
        assert run.status == RunStatus.error and outage["attempts"] == 3

        # 3. A limit the user set is not retried, even with retries left.
        print(
            "\nCase 3: max_turns=1 with retries=2. A 'not retrying' warning and one ERROR are expected:"
        )
        simulate_outages(0)
        limited = ClaudeAgent(
            id="limited-demo",
            model="claude-sonnet-4-6",
            db=db,
            cwd=workdir,
            allowed_tools=["Bash"],
            permission_mode="bypassPermissions",
            max_turns=1,
            max_budget_usd=0.5,
            retries=2,
            delay_between_retries=1,
        )
        run = limited.run(
            "Run `echo one` with Bash, then `echo two` in a separate Bash call, then reply DONE.",
            session_id="limit",
        )
        print(
            f"max_turns=1 with retries=2: attempts: {outage['attempts']}, status: {run.status}"
        )
        assert run.status == RunStatus.error and outage["attempts"] == 1

        # 4. The default is no retries.
        print("\nCase 4: retries=0, the default. One ERROR and no retry are expected:")
        simulate_outages(1)
        plain = ClaudeAgent(
            id="plain-demo",
            model="claude-sonnet-4-6",
            db=db,
            cwd=workdir,
            allowed_tools=[],
            max_turns=2,
        )
        run = plain.run("Reply with exactly OK.", session_id="plain")
        print(
            f"retries=0 (default): attempts: {outage['attempts']}, status: {run.status}"
        )
        assert run.status == RunStatus.error and outage["attempts"] == 1


if __name__ == "__main__":
    main()
