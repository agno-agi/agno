from textwrap import dedent
from typing import Final

CREATE_TABLE_QUERY: Final[str] = dedent("""
    DEFINE TABLE IF NOT EXISTS {table} SCHEMAFUL;

    DEFINE FIELD IF NOT EXISTS memory ON {table} FLEXIBLE TYPE object;
    DEFINE FIELD IF NOT EXISTS user ON {table} TYPE record<user>;
    DEFINE FIELD IF NOT EXISTS time ON {table} TYPE object DEFAULT ALWAYS {{}};
    DEFINE FIELD IF NOT EXISTS time.created_at ON {table} TYPE datetime VALUE time::now() READONLY;
    DEFINE FIELD IF NOT EXISTS time.updated_at ON {table} TYPE datetime VALUE time::now() READONLY;

    DEFINE INDEX IF NOT EXISTS idx_{table}_user ON {table} FIELDS user;
""")
