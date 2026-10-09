"""
Compact a Codex thread behind an Agno session
=============================================
Codex keeps each conversation in its own thread and compacts it when the
context window fills up. CodexAgent.compact / acompact asks the app-server
to do that now for the thread behind an Agno session, replacing the older
turns with a summary. The next run on the session continues from the summary.

Scenario: seed a fact, add a few turns including a long document, compact,
then ask for the fact again on the same session.

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


async def main():
    with tempfile.TemporaryDirectory(prefix="agno-codex-compaction-") as workdir:
        agent = CodexAgent(
            id="codex-compaction",
            model="gpt-5.6-luna",
            sandbox="read-only",
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

        # 2. Compact the thread. This resumes it in the app-server, requests the compaction
        #    and waits for the thread to be idle again.
        compacted = await agent.acompact(SESSION_ID)
        print(f"Compacted: {compacted}")
        assert compacted is True

        # 3. The next turn continues from the summary.
        run = await agent.arun(
            "What is the release codename? Reply with just the codename.",
            session_id=SESSION_ID,
        )
        assert run.status == RunStatus.completed, run.content
        print(f"After compaction: {run.content}")
        assert "tangerine-walrus-88" in (run.content or "")


if __name__ == "__main__":
    asyncio.run(main())
