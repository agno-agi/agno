"""Unit tests for the search_learnings query surface.

The sqlite path is proven here against a real SqliteDb; the postgres and
async_postgres paths share the same statement shape and are covered by the
integration suite. The base-class default must raise NotImplementedError so
stores know to fall back to their client-side scan.
"""

import pytest

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.sqlite import SqliteDb
from agno.db.utils import learning_search_patterns


@pytest.fixture
def db(tmp_path) -> SqliteDb:
    return SqliteDb(db_file=str(tmp_path / "learnings.db"))


def _seed(db: SqliteDb, id: str, content: dict, **kwargs) -> None:
    db.upsert_learning(id=id, learning_type=kwargs.pop("learning_type", "entity_memory"), content=content, **kwargs)


class TestPatterns:
    def test_space_and_underscore_variants(self) -> None:
        assert learning_search_patterns("sarah chen") == ["%sarah chen%", "%sarah_chen%"]
        assert learning_search_patterns("sarah_chen") == ["%sarah_chen%", "%sarah chen%"]
        assert learning_search_patterns("radar") == ["%radar%"]

    def test_empty_query_yields_no_patterns(self) -> None:
        assert learning_search_patterns("   ") == []


class TestBaseDefaults:
    def test_base_db_default_raises(self) -> None:
        assert BaseDb.search_learnings.__qualname__ == "BaseDb.search_learnings"
        with pytest.raises(NotImplementedError):
            BaseDb.search_learnings(object(), query="x")  # type: ignore[arg-type]

    async def test_async_base_db_default_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            await AsyncBaseDb.search_learnings(object(), query="x")  # type: ignore[arg-type]


class TestSqliteSearchLearnings:
    def test_matches_content_case_insensitively(self, db: SqliteDb) -> None:
        _seed(db, "e1", {"entity_id": "acme_corp", "facts": [{"content": "Uses PostgreSQL"}]}, entity_id="acme_corp")
        rows = db.search_learnings(query="postgresql")
        assert [r["learning_id"] for r in rows] == ["e1"]

    def test_search_crosses_slug_boundary(self, db: SqliteDb) -> None:
        _seed(db, "e1", {"entity_id": "sarah_chen", "name": "sarah_chen"}, entity_id="sarah_chen")
        _seed(db, "e2", {"entity_id": "acme_corp", "name": "acme_corp"}, entity_id="acme_corp")
        assert [r["learning_id"] for r in db.search_learnings(query="sarah chen")] == ["e1"]
        assert [r["learning_id"] for r in db.search_learnings(query="Acme Corp")] == ["e2"]
        # And the reverse direction: an underscore query finds spaced content
        _seed(db, "e3", {"entity_id": "jane_doe", "name": "Jane Doe"}, entity_id="jane_doe")
        assert any(r["learning_id"] == "e3" for r in db.search_learnings(query="jane_doe"))

    def test_finds_match_outside_recent_window(self, db: SqliteDb) -> None:
        # Insert 100 entities, then touch 40 of them so the needle row is far
        # outside any recency window. The old over-fetch path scanned only the
        # most recently updated rows and missed this by construction.
        _seed(db, "needle", {"entity_id": "old_needle", "facts": [{"content": "the rare zanzibar detail"}]})
        for i in range(99):
            _seed(db, f"filler-{i}", {"entity_id": f"filler_{i}", "facts": [{"content": f"filler fact {i}"}]})
        for i in range(40):
            _seed(db, f"filler-{i}", {"entity_id": f"filler_{i}", "facts": [{"content": f"updated filler {i}"}]})

        rows = db.search_learnings(query="zanzibar", limit=5)
        assert [r["learning_id"] for r in rows] == ["needle"]

    def test_filters_and_order(self, db: SqliteDb) -> None:
        _seed(db, "a", {"x": "same needle"}, namespace="global", entity_type="person")
        _seed(db, "b", {"x": "same needle"}, namespace="global", entity_type="project")
        _seed(db, "c", {"x": "same needle"}, namespace="private", entity_type="person")
        _seed(db, "a", {"x": "same needle updated"}, namespace="global", entity_type="person")

        rows = db.search_learnings(query="needle", namespace="global")
        assert [r["learning_id"] for r in rows] == ["a", "b"] or [r["learning_id"] for r in rows] == ["b", "a"]

        rows = db.search_learnings(query="needle", namespace="global", entity_type="person")
        assert [r["learning_id"] for r in rows] == ["a"]

        rows = db.search_learnings(query="needle", limit=2)
        assert len(rows) == 2

    def test_empty_query_returns_empty(self, db: SqliteDb) -> None:
        _seed(db, "a", {"x": "content"})
        assert db.search_learnings(query="   ") == []

    def test_search_fails_loudly_on_db_error(self, db: SqliteDb, monkeypatch: pytest.MonkeyPatch) -> None:
        # get_learnings swallows db errors into []; search_learnings must not.
        _seed(db, "a", {"x": "content"})

        def broken_session() -> None:
            raise RuntimeError("connection lost")

        monkeypatch.setattr(db, "Session", broken_session)
        with pytest.raises(RuntimeError, match="connection lost"):
            db.search_learnings(query="content")
        # ...while get_learnings demonstrates today's swallowing behavior
        assert db.get_learnings() == []
