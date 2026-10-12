"""
Compact a Codex thread behind an Agno session
=============================================
Codex keeps each conversation in its own thread and compacts it when the
context window fills up. CodexAgent.compact / acompact asks the app-server
to do that now for the thread behind an Agno session, replacing the older
turns with a summary. The next run on the session continues from the summary.

The agent here uses a full-access sandbox, developer instructions and an
approval mode. Compaction resumes the thread with the same options as a run,
so all of them apply to the resumed thread.

Scenario:
1. Seed a fact and add a few turns including a long document.
2. Compact, then ask for the fact again on the same session.
3. The guards: compaction refuses while a background run on the session is
   still in flight, and returns False when the stored thread no longer exists.
   The last step logs a warning on purpose: the adapter reports whenever it
   drops a thread reference it can no longer resume.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_compaction.py
"""

import asyncio
import tempfile

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus

SESSION_ID = "codex-compaction-demo"
FACT = "The release codename is tangerine-walrus-88."
FINAL = {RunStatus.completed, RunStatus.error, RunStatus.cancelled}


async def wait_for_run(agent: CodexAgent, run_id: str, timeout: float = 180.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        stored = await agent.aget_run_output(run_id, SESSION_ID)
        if stored is not None and stored.status in FINAL:
            return stored
        await asyncio.sleep(1.0)
    raise TimeoutError(f"run {run_id} did not finish in {timeout}s")


async def main():
    with tempfile.TemporaryDirectory(prefix="agno-codex-compaction-") as workdir:
        agent = CodexAgent(
            id="codex-compaction",
            model="gpt-5.6-luna",
            sandbox="full-access",
            approval_mode="deny_all",
            instructions="Answer in as few words as possible.",
            db=SqliteDb(db_file=f"{workdir}/runs.db"),
            cwd=workdir,
        )

        # No thread exists before the first run, so there is nothing to compact yet.
        assert await agent.acompact(SESSION_ID) is False

        # 1. Build up a conversation.
        run = await agent.arun(
            f"Remember this: {FACT} Reply with just OK.", session_id=SESSION_ID
        )
        assert run.status == RunStatus.completed, run.content
        document = " ".join(
            f"Line {i}: the quick brown fox jumps over the lazy dog number {i}."
            for i in range(1200)
        )
        for prompt in [
            "Keep this document in mind and reply with just OK: " + document,
            "Name three primary colors, comma separated.",
            "What is 17 times 3? Reply with just the number.",
        ]:
            run = await agent.arun(prompt, session_id=SESSION_ID)
            assert run.status == RunStatus.completed, run.content
            print(f"Turn: {run.content!r}")

        # 2. Compact the thread. This resumes it in the app-server with the agent's sandbox,
        #    instructions and approval mode, requests the compaction and waits for the thread
        #    to be idle again. The next turn continues from the summary.
        compacted = await agent.acompact(SESSION_ID)
        print(f"Compacted: {compacted}")
        assert compacted is True
        run = await agent.arun(
            "What is the release codename? Reply with just the codename.",
            session_id=SESSION_ID,
        )
        assert run.status == RunStatus.completed, run.content
        print(f"After compaction: {run.content}")
        assert "tangerine-walrus-88" in (run.content or "")

        # 3a. Compaction opens its own app-server on the thread, so it refuses while a run on
        #     the session is in flight; two processes must not append to one rollout.
        pending = await agent.arun(
            "Reply with just OK.", session_id=SESSION_ID, background=True
        )
        try:
            await agent.acompact(SESSION_ID)
            raise AssertionError("compaction should refuse while a run is in flight")
        except RuntimeError as error:
            print(f"While a run is in flight: {error}")
        finished = await wait_for_run(agent, pending.run_id)
        assert finished.status == RunStatus.completed, finished.content
        assert await agent.acompact(SESSION_ID) is True
        print("After the run finished: compacted again")

        # 3b. A stored thread id whose rollout no longer exists is forgotten, as a run would
        #     do, and compaction reports there was nothing to compact. The adapter logs a
        #     warning when it drops a thread reference; the one printed next is expected.
        print(
            "Pointing the session at a thread that does not exist; the next warning is expected:"
        )
        session = await agent.aget_session(SESSION_ID)
        session.session_data["codex_thread_id"] = "01a121ff-0000-7000-8000-000000000000"
        await agent.aupsert_session(session)
        assert await agent.acompact(SESSION_ID) is False
        session = await agent.aget_session(SESSION_ID)
        assert "codex_thread_id" not in (session.session_data or {})
        print("Stale thread id: compaction returned False and the id was forgotten")


if __name__ == "__main__":
    asyncio.run(main())
