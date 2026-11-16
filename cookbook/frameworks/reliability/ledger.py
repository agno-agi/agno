"""Test-only durable turn budget and controllable tool receipts.

All local replica processes share this fixture ledger, but never SDK transcript
files. Production run/session/queue persistence is exercised separately in Postgres.
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@contextmanager
def connect():
    path = Path(os.environ["HARNESS_LEDGER"])
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS attempts
        (id TEXT PRIMARY KEY, provider TEXT, replica TEXT, started REAL);
        CREATE TABLE IF NOT EXISTS receipts
        (id INTEGER PRIMARY KEY, case_id TEXT, step TEXT, replica TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS gates (case_id TEXT PRIMARY KEY, released INTEGER);
    """)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def reserve(provider: str) -> None:
    """Count every native SDK submission before it can execute, including retries."""
    deadline = datetime.fromisoformat(
        os.environ["HARNESS_DEADLINE_UTC"].replace("Z", "+00:00")
    )
    if datetime.now(timezone.utc) >= deadline:
        raise RuntimeError("Overnight execution deadline reached")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
        if count >= 200:
            raise RuntimeError("Overnight live SDK budget exhausted (200 attempts)")
        db.execute(
            "INSERT INTO attempts VALUES (?, ?, ?, ?)",
            (str(uuid4()), provider, os.environ["HARNESS_REPLICA"], time.time()),
        )


def instrument_sdk(provider: str) -> None:
    """Instrument only this test process, without changing framework code."""
    if provider == "claude":
        from claude_agent_sdk import ClaudeSDKClient

        original = ClaudeSDKClient.query

        async def query(self, *args, **kwargs):
            reserve("claude")
            return await original(self, *args, **kwargs)

        ClaudeSDKClient.query = query
    else:
        from openai_codex import AsyncThread

        original = AsyncThread.turn

        async def turn(self, *args, **kwargs):
            reserve("codex")
            return await original(self, *args, **kwargs)

        AsyncThread.turn = turn
