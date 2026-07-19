"""Integration tests for SqliteDb knowledge-content queries."""

from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.sqlite.sqlite import SqliteDb


def _make_db(tmp_path) -> SqliteDb:
    return SqliteDb(db_file=str(tmp_path / "knowledge.db"))


def test_get_knowledge_contents_sorts_string_columns(tmp_path):
    """String columns (e.g. ``name``) must sort lexicographically.

    Regression: sorting was ``column * (1 | -1)``, which SQLite coerces text
    to numeric ``0`` — every row tied, so string sorts were a no-op in both
    directions (numeric columns happened to work, which is why it was missed).
    """
    db = _make_db(tmp_path)
    for name in ["charlie", "alpha", "bravo", "delta"]:
        db.upsert_knowledge_content(KnowledgeRow(name=name, description="d"))

    asc, _ = db.get_knowledge_contents(sort_by="name", sort_order="asc")
    desc, _ = db.get_knowledge_contents(sort_by="name", sort_order="desc")

    assert [r.name for r in asc] == ["alpha", "bravo", "charlie", "delta"]
    assert [r.name for r in desc] == ["delta", "charlie", "bravo", "alpha"]


def test_get_knowledge_contents_sorts_numeric_columns(tmp_path):
    """Numeric sorting (the previously-working path) is unaffected."""
    db = _make_db(tmp_path)
    for size in [300, 100, 200]:
        db.upsert_knowledge_content(KnowledgeRow(name=f"n{size}", description="d", size=size))

    asc, _ = db.get_knowledge_contents(sort_by="size", sort_order="asc")

    assert [r.size for r in asc] == [100, 200, 300]
