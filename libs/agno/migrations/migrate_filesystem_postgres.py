"""Upgrade the Agno filesystem table (``agno_fs``) on PostgreSQL to the v3.1 schema.

v3.1 keys the table by ``(namespace, user_id, path)``. A table created by an
earlier release is keyed by ``(namespace, path)`` and is refused until it is
upgraded, so the change to the key is a deliberate step and never runs on its
own. Rows keep their namespace and land in the shared partition; nothing is lost.

Run it once, with the application stopped and a backup taken:

    python libs/agno/migrations/migrate_filesystem_postgres.py

The upgrade is idempotent: running it on a current table changes nothing.
"""

from agno.db.postgres import PostgresDb
from agno.fs.db import DbFileSystem

# Use the same database your agents' filesystems live in.
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# The defaults match FileSystem(db): table "agno_fs" in the "fs" schema. Pass
# table_name= / db_schema= here if the application overrides them.
backend = DbFileSystem(db=db)

if __name__ == "__main__":
    if backend.upgrade_schema():
        print(f"Upgraded {backend.table.fullname} to the (namespace, user_id, path) key.")
    else:
        print(f"{backend.table.fullname} is already current; nothing to do.")
