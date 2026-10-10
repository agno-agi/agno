"""Durable Claude transcripts: watch the agno_transcripts table fill up and drive a resume.

Claude Code keeps each conversation as a JSONL transcript on the local disk of the
machine that ran it. With a database that supports transcript storage, ClaudeAgent
mirrors every transcript line into the agno_transcripts table, and a later turn on any
machine resumes the conversation from the database instead of the local file.

This example runs the whole flow in one go and prints the table after each step:

1. Replica A runs a turn and stores a fact. The transcript lines land in agno_transcripts.
2. Replica B is a second agent instance with a different working directory, so the local
   transcript from replica A is invisible to it. It resumes from the database, answers
   from the stored conversation, and appends its own lines to the same transcript.

Requirements: a logged-in Claude Code CLI (claude login) or ANTHROPIC_API_KEY.

Run:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/transcript_store.py
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/transcript_store.py --postgres

The --postgres flag uses the container started by cookbook/scripts/run_pgvector.sh.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.db.base import BaseDb
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus
from sqlalchemy import text

AGENT_ID = "transcript-store-demo"
SECRET = "cobalt-orchard-742"
WORKDIR = Path("tmp/transcript-store")


def make_db(postgres: bool) -> BaseDb:
    if postgres:
        return PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
    WORKDIR.mkdir(parents=True, exist_ok=True)
    return SqliteDb(db_file=str(WORKDIR / "transcripts.db"))


def make_agent(db: BaseDb, replica: str) -> ClaudeAgent:
    """One ClaudeAgent per replica. The shared id keeps the transcript project key stable."""
    cwd = WORKDIR / replica
    cwd.mkdir(parents=True, exist_ok=True)
    return ClaudeAgent(
        id=AGENT_ID,
        name="Transcript Store Demo",
        db=db,
        cwd=str(cwd),
        allowed_tools=[],
        max_turns=2,
        max_budget_usd=0.5,
    )


def transcript_rows(
    db: BaseDb, project_key: str, sdk_session_id: str
) -> List[Dict[str, Any]]:
    """Read the mirrored transcript straight from the table, in append order."""
    table = db.transcripts_table_name
    schema = getattr(db, "db_schema", None)
    if schema:
        table = f"{schema}.{table}"
    query = text(
        f"SELECT position, subpath, entry FROM {table} "
        "WHERE project_key = :project_key AND session_id = :session_id ORDER BY position"
    )
    with db.db_engine.connect() as connection:
        result = connection.execute(
            query, {"project_key": project_key, "session_id": sdk_session_id}
        )
        return [
            {"position": row[0], "subpath": row[1] or "", "entry": json.loads(row[2])}
            for row in result.fetchall()
        ]


def describe_entry(entry: Dict[str, Any]) -> str:
    """One line of detail for a transcript entry: role and a snippet of what it holds."""
    message = entry.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return f"{message.get('role')}: {content[:60]!r}"
    if isinstance(content, list):
        parts = []
        for block in content:
            kind = block.get("type")
            if kind == "text":
                parts.append(f"text {block.get('text', '')[:50]!r}")
            elif kind == "tool_use":
                parts.append(f"tool_use {block.get('name')}")
            elif kind == "tool_result":
                parts.append("tool_result")
            else:
                parts.append(str(kind))
        return f"{message.get('role')}: " + ", ".join(parts)
    return ""


def print_table(
    title: str, rows: Sequence[Dict[str, Any]], since_position: int = 0
) -> None:
    print()
    print(title)
    print(f"{'position':>8}  {'type':<22} {'uuid':<10} detail")
    for row in rows:
        marker = "+" if row["position"] > since_position else " "
        entry = row["entry"]
        uuid = (entry.get("uuid") or "")[:8]
        print(
            f"{marker}{row['position']:>7}  {entry.get('type', ''):<22} {uuid:<10} {describe_entry(entry)}"
        )
    print(
        f"{len(rows)} rows"
        + (
            f", {sum(1 for r in rows if r['position'] > since_position)} new"
            if since_position
            else ""
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show Claude transcripts being mirrored to the database and resumed."
    )
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Use the pgvector container instead of SQLite",
    )
    args = parser.parse_args()

    db = make_db(args.postgres)
    agno_session_id = f"demo-{uuid4().hex[:8]}"
    print(f"Database: {type(db).__name__}")
    print(f"Agno session: {agno_session_id}")

    # Step 1: replica A stores a fact. The SDK mirrors the transcript as it is written.
    print()
    print("Step 1: replica A runs the first turn")
    replica_a = make_agent(db, "replica-a")
    first = replica_a.run(
        f"Remember this: the deploy password is {SECRET}. Reply with exactly: OK",
        session_id=agno_session_id,
        user_id="demo-user",
    )
    assert first.status == RunStatus.completed, first.content
    print(f"Reply: {first.content}")

    session = replica_a.read_or_create_session(agno_session_id)
    sdk_session_id = session.session_data["claude_sdk_session_id"]
    project_key = replica_a.project_key or replica_a.get_id()
    print(f"Claude session id stored on the Agno session: {sdk_session_id}")
    print(f"Transcript project key: {project_key}")

    rows_after_a = transcript_rows(db, project_key, sdk_session_id)
    assert rows_after_a, (
        "No transcript rows were mirrored. Does this database support transcript storage?"
    )
    print_table("agno_transcripts after replica A:", rows_after_a)
    last_position = rows_after_a[-1]["position"]

    # Step 2: replica B has a different working directory, so it cannot see replica A's
    # local transcript. The SDK loads the transcript from the database and resumes it.
    print()
    print(
        "Step 2: replica B resumes the same Agno session from another working directory"
    )
    replica_b = make_agent(db, "replica-b")
    second = replica_b.run(
        "What is the deploy password? Reply with only the password.",
        session_id=agno_session_id,
        user_id="demo-user",
    )
    assert second.status == RunStatus.completed, second.content
    print(f"Reply: {second.content}")
    assert SECRET in str(second.content), (
        "Replica B did not recall the fact from the stored transcript"
    )

    resumed_id = replica_b.read_or_create_session(agno_session_id).session_data[
        "claude_sdk_session_id"
    ]
    assert resumed_id == sdk_session_id, (
        f"Expected the same Claude session, got {resumed_id}"
    )
    print(f"Claude session id after resume: {resumed_id} (unchanged)")

    rows_after_b = transcript_rows(db, project_key, sdk_session_id)
    print_table(
        "agno_transcripts after replica B (new rows marked +):",
        rows_after_b,
        since_position=last_position,
    )
    assert len(rows_after_b) > len(rows_after_a), (
        "Replica B did not append to the transcript"
    )

    print()
    print(
        "PASS: the transcript was mirrored to the database, resumed from it by a second replica, and extended."
    )


if __name__ == "__main__":
    main()
