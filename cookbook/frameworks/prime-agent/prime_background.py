"""Submit a background run and poll its persisted terminal result.

SQLite is used for this local demonstration. Keep the process running until
completion: background=True uses Agno's in-process background runtime.
"""

import asyncio
import tempfile
from os import getenv
from pathlib import Path
from uuid import uuid4

from agno.agents.prime import PrimeAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agno-prime-background-") as state_dir:
        agent = PrimeAgent(
            id="prime-background",
            cwd=getenv("PRIME_AGENT_CWD", "."),
            db=SqliteDb(db_file=str(Path(state_dir) / "runs.db")),
            timeout=120,
        )
        session_id = str(uuid4())
        run_id = str(uuid4())
        completed = False
        try:
            accepted = await agent.arun(
                "Reply with exactly BACKGROUND_OK.",
                session_id=session_id,
                run_id=run_id,
                background=True,
            )
            print(f"Accepted run: {accepted.run_id} | {accepted.status.value}")
            deadline = asyncio.get_running_loop().time() + 150
            while asyncio.get_running_loop().time() < deadline:
                run = await agent.aget_run_output(run_id, session_id)
                if run is not None and run.status in (
                    RunStatus.completed,
                    RunStatus.error,
                    RunStatus.cancelled,
                ):
                    completed = True
                    assert run.status == RunStatus.completed, run.content
                    assert "BACKGROUND_OK" in str(run.content), run.content
                    print(f"Stored result: {run.content} | {run.status.value}")
                    return
                await asyncio.sleep(0.5)
            raise TimeoutError(
                "The background run did not reach a terminal state within 150 seconds"
            )
        finally:
            if not completed:
                await agent.acancel_run(run_id)
                # Allow the background worker to persist cancellation before its local DB is removed.
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    run = await agent.aget_run_output(run_id, session_id)
                    if run is not None and run.status in (
                        RunStatus.completed,
                        RunStatus.error,
                        RunStatus.cancelled,
                    ):
                        break
                    await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
