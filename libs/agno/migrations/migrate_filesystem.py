"""Upgrade the Agno filesystem table (``agno_fs``) to the v3.1 schema.

v3.1 keys the table by ``(namespace, user_id, path)``. A table created by an
earlier release is keyed by ``(namespace, path)`` and is refused until it is
upgraded, so the change to the key is a deliberate step and never runs on its
own. Rows keep their namespace and land in the shared partition; nothing is lost.

Run it once per database, with the application stopped:

    python libs/agno/migrations/migrate_filesystem.py

Take a backup first. The upgrade is idempotent: running it on a current table
changes nothing.
"""

from agno.fs.db import DbFileSystem

# Point this at the database your agents' filesystems live in. Pass the same
# db_url (or the same SqliteDb / PostgresDb via db=...) the application uses.
# The defaults match FileSystem(db): table "agno_fs", schema "fs" on PostgreSQL.
backend = DbFileSystem(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    # table_name="agno_fs",
    # db_schema="fs",
)

# For SQLite:
# backend = DbFileSystem(db_url="sqlite:///tmp/agent.db")

if __name__ == "__main__":
    if backend.upgrade_schema():
        print("Upgraded", backend.table.fullname, "to the (namespace, user_id, path) key.")
    else:
        print(backend.table.fullname, "is already current; nothing to do.")
