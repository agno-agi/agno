"""BUG-016: `or`+ternary precedence causes ID collisions across DB/vectordb modules.

Python parses `a or b if c else d` as `(a or b) if c else d`,
NOT the intended `a or (b if c else d)`.

When db_engine=None (common), the entire chain is skipped.
"""

import pytest


class TestBUG016DbIdCollisions:
    def test_sqlite_same_id_different_urls(self):
        """Two SqliteDb with different db_url get the same generated ID."""
        from agno.db.sqlite.sqlite import SqliteDb

        db1 = SqliteDb(db_url="sqlite:///db1.db")
        db2 = SqliteDb(db_url="sqlite:///db2.db")
        assert db1.id == db2.id, "Bug not present — different URLs now produce different IDs"

    def test_sqlite_same_id_different_files(self):
        """Two SqliteDb with different db_file get the same generated ID."""
        from agno.db.sqlite.sqlite import SqliteDb

        db1 = SqliteDb(db_file="file1.db")
        db2 = SqliteDb(db_file="file2.db")
        assert db1.id == db2.id, "Bug not present — different files now produce different IDs"

    def test_ternary_precedence_proof(self):
        """Prove the precedence bug: `a or b if c else d` ignores a when c is falsy."""
        db_url = "sqlite:///custom.db"
        db_file = None
        db_engine = None

        result = db_url or db_file or str(db_engine) if db_engine else "sqlite:///agno.db"
        assert result == "sqlite:///agno.db", (
            "Expected fallback despite db_url being set — "
            "Python parsed as (db_url or db_file or str(db_engine)) if db_engine else default"
        )

        result_fixed = db_url or db_file or (str(db_engine) if db_engine else "sqlite:///agno.db")
        assert result_fixed == "sqlite:///custom.db", "With parens, db_url is correctly used"
