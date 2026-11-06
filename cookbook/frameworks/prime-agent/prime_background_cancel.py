"""Cancel a live background stream and check its persisted cancelled result.

Cancellation is requested after the first text chunk. The long prompt keeps
text generation active long enough to exercise CLI interruption.
"""

import asyncio
import json
from os import getenv
from uuid import uuid4

from agno.agents.prime import PrimeAgent
from agno.db.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

agent = PrimeAgent(
    id="prime-background-cancel",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    db=SqliteDb(db_file="tmp/prime_background_cancel.db"),
    timeout=120,
)


async def main() -> None:
    session_id = str(uuid4())
    run_id = str(uuid4())
    cancelled = False
    result = None
    stream = agent.arun(
        "List every integer from 1 through 5000, spelling each one in English. "
        "Do not use tools; write the full list directly in your answer.",
        session_id=session_id,
        run_id=run_id,
        stream=True,
        background=True,
        yield_run_output=True,
    )
    try:
        async for item in stream:
            if isinstance(item, RunOutput):
                result = item
                continue
            # Background streams carry SSE strings rather than event objects.
            for line in item.splitlines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if (
                    event.get("event") == "RunContent"
                    and event.get("content")
                    and not cancelled
                ):
                    await agent.acancel_run(run_id)
                    cancelled = True
                    print(f"Cancellation requested for {run_id}")
    finally:
        if result is None:
            await agent.acancel_run(run_id)
        await stream.aclose()

    assert cancelled, "No text arrived to cancel; inspect the CLI run result"
    assert result is not None and result.status == RunStatus.cancelled, result
    stored = await agent.aget_run_output(run_id, session_id)
    assert stored is not None and stored.status == RunStatus.cancelled, stored
    print("PASS: interrupted the CLI run and persisted CANCELLED")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=150))
