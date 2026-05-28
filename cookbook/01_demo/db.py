"""
Database
========

Local SQLite for agent sessions + memory.
Stored at ``data/demo.db`` next to this cookbook (gitignored).
"""

from pathlib import Path

from agno.db.sqlite import SqliteDb

DB_ID = "demo-db"
DB_FILE = str(Path(__file__).parent / "data" / "demo.db")

# Ensure the data directory exists before SqliteDb opens the file.
Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)


def get_db() -> SqliteDb:
    """Local SQLite database for agent sessions + memory."""
    return SqliteDb(id=DB_ID, db_file=DB_FILE)
