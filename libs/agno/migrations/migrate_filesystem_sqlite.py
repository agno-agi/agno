"""Upgrade the Agno filesystem table (``agno_fs``) on SQLite to the v3.1 schema.

v3.1 keys the table by ``(namespace, user_id, path)``. A table created by an
earlier release is keyed by ``(namespace, path)`` and is refused until it is
upgraded, so the change to the key is a deliberate step and never runs on its
own. SQLite cannot change a key in place, so the table is rebuilt and swapped in
one transaction. Rows keep their namespace and land in the shared partition;
nothing is lost.

Run it once per database file, with the application stopped and a copy of the
file taken:

    python libs/agno/migrations/migrate_filesystem_sqlite.py

The upgrade is idempotent: running it on a current table changes nothing.
"""

from agno.db.sqlite import SqliteDb
from agno.fs.db import DbFileSystem

# Use the same database file your agents' filesystems live in.
db = SqliteDb(db_file="tmp/data.db")

# The default table matches FileSystem(db): "agno_fs". Pass table_name= here if
# the application overrides it.
backend = DbFileSystem(db=db)

if __name__ == "__main__":
    if backend.upgrade_schema():
        print(f"Upgraded {backend.table.fullname} to the (namespace, user_id, path) key.")
    else:
        print(f"{backend.table.fullname} is already current; nothing to do.")
