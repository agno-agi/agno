"""
Compact a Claude conversation and keep going from the database
==============================================================
Claude Code compacts a long conversation into a summary, on its own when
the context window fills up or when asked with /compact. Through Agno the
slash command is just a run input, and with transcript storage the
compaction is written to the agno_transcripts table like every other
transcript line: a compact_boundary system entry followed by the summary.

Scenario: seed a fact, add a few turns including a long document, send
/compact, print the transcript rows the compaction produced, then start a
second agent instance with a different working directory. It resumes from
the database alone and answers from the summary.

Requirements:
    pip install claude-agent-sdk
    A database with transcript storage (SQLite or PostgreSQL).

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/compaction.py
"""

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path

from claude_agent_sdk import HookMatcher

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus

SESSION_ID = "compaction-demo"
FACT = "The release codename is tangerine-walrus-88."

compactions = []


async def on_pre_compact(input_data, tool_use_id, context):
    """Claude Code hook: fires before each compaction with trigger 'manual' or 'auto'."""
    compactions.append(input_data.get("trigger"))
    return {}


def compaction_rows(db_file: str):
    """Transcript rows written by the compaction: the boundary marker and the summary."""
    connection = sqlite3.connect(db_file)
    rows = connection.execute(
        "select position, entry from agno_transcripts order by position"
    ).fetchall()
    connection.close()
    found = []
    for position, raw in rows:
        entry = json.loads(raw)
        if entry.get("type") == "system" and entry.get("subtype") == "compact_boundary":
            found.append((position, "compact_boundary", str(entry.get("content"))))
        elif entry.get("type") == "user" and entry.get("isCompactSummary"):
            summary = entry.get("message", {}).get("content", "")
            found.append(
                (position, "compact_summary", str(summary)[:160].replace("\n", " "))
            )
    return len(rows), found


async def main():
    with tempfile.TemporaryDirectory(prefix="agno-compaction-") as root:
        db_file = str(Path(root) / "runs.db")

        def make_agent(name: str) -> ClaudeAgent:
            workdir = Path(root) / name
            workdir.mkdir()
            return ClaudeAgent(
                id="compaction-demo",
                model="claude-sonnet-4-6",
                db=SqliteDb(db_file=db_file),
                cwd=str(workdir),
                allowed_tools=[],
                max_turns=2,
                max_budget_usd=0.5,
                options_kwargs={
                    "hooks": {"PreCompact": [HookMatcher(hooks=[on_pre_compact])]}
                },
            )

        replica_a = make_agent("replica-a")

        # 1. Build up a conversation. A very short one cannot be compacted.
        run = await replica_a.arun(
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
            run = await replica_a.arun(prompt, session_id=SESSION_ID)
            assert run.status == RunStatus.completed, run.content
        total, found = compaction_rows(db_file)
        print(f"Before /compact: {total} transcript rows, {len(found)} compaction rows")

        # 2. Ask Claude Code to compact. The slash command is an ordinary run input.
        run = await replica_a.arun("/compact", session_id=SESSION_ID)
        assert run.status == RunStatus.completed, run.content
        assert compactions == ["manual"], compactions
        total, found = compaction_rows(db_file)
        print(
            f"After /compact: {total} transcript rows, PreCompact hook saw {compactions}"
        )
        for position, kind, text in found:
            print(f"  row {position} {kind}: {text}")
        assert [kind for _, kind, _ in found] == ["compact_boundary", "compact_summary"]

        # 3. A second instance with a different working directory has no local transcript.
        #    It resumes from the database and answers from the compacted summary.
        replica_b = make_agent("replica-b")
        run = await replica_b.arun(
            "What is the release codename? Reply with just the codename.",
            session_id=SESSION_ID,
        )
        assert run.status == RunStatus.completed, run.content
        print(f"Replica B after compaction: {run.content}")
        assert "tangerine-walrus-88" in (run.content or "")


if __name__ == "__main__":
    asyncio.run(main())
