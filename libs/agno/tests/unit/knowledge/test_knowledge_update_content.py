"""Unit tests for Knowledge._update_content and Knowledge._aupdate_content.

Regression tests for issue #7754: the methods used to early-return None
when the content row was missing in the database, silently dropping the
caller's data instead of upserting the new row.
"""


from agno.db.sqlite import SqliteDb
from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.knowledge import Knowledge


def _make_knowledge(tmp_path) -> Knowledge:
    db = SqliteDb(db_file=str(tmp_path / "test.db"))
    return Knowledge(contents_db=db)


class TestUpdateContentUpsert:
    """Sync _update_content must upsert a missing row, not bail."""

    def test_missing_row_is_inserted_with_full_content(self, tmp_path):
        knowledge = _make_knowledge(tmp_path)
        new_content = Content(
            id="missing-row-id",
            name="New name",
            description="New description",
            status=ContentStatus.COMPLETED,
            metadata={"source": "test"},
        )

        assert knowledge.contents_db.get_knowledge_content("missing-row-id") is None  # type: ignore[union-attr]

        result = knowledge._update_content(new_content)

        assert result is not None
        assert result["id"] == "missing-row-id"
        assert result["name"] == "New name"
        assert result["description"] == "New description"
        assert result["status"] == "completed"
        assert result["metadata"] == {"source": "test"}

        # Verify the row is now in the DB.
        stored = knowledge.contents_db.get_knowledge_content("missing-row-id")  # type: ignore[union-attr]
        assert stored is not None
        assert stored.id == "missing-row-id"  # type: ignore[union-attr]
        assert stored.name == "New name"  # type: ignore[union-attr]
        assert stored.description == "New description"  # type: ignore[union-attr]

    def test_existing_row_is_updated_in_place(self, tmp_path):
        knowledge = _make_knowledge(tmp_path)

        # First call inserts the row.
        original = Content(
            id="existing-id",
            name="Original name",
            description="Original description",
            status=ContentStatus.PROCESSING,
        )
        knowledge._update_content(original)

        # Second call updates the same row.
        updated = Content(
            id="existing-id",
            name="Updated name",
            description="Updated description",
            status=ContentStatus.COMPLETED,
        )
        result = knowledge._update_content(updated)

        assert result is not None
        assert result["name"] == "Updated name"
        assert result["description"] == "Updated description"
        assert result["status"] == "completed"

        # DB still has exactly one row, not a duplicate.
        stored = knowledge.contents_db.get_knowledge_content("existing-id")  # type: ignore[union-attr]
        assert stored is not None
        assert stored.name == "Updated name"  # type: ignore[union-attr]
        assert stored.description == "Updated description"  # type: ignore[union-attr]

    def test_missing_id_returns_none(self, tmp_path):
        """The pre-existing check for `content.id is None` must still work."""
        knowledge = _make_knowledge(tmp_path)
        result = knowledge._update_content(Content(name="no-id"))
        assert result is None


class TestAUpdateContentUpsert:
    """Async _aupdate_content must mirror the sync behavior."""

    async def test_missing_row_is_inserted_with_full_content(self, tmp_path):
        knowledge = _make_knowledge(tmp_path)
        new_content = Content(
            id="async-missing-id",
            name="Async new name",
            description="Async new description",
            status=ContentStatus.COMPLETED,
        )

        result = await knowledge._aupdate_content(new_content)

        assert result is not None
        assert result["id"] == "async-missing-id"
        assert result["name"] == "Async new name"
        assert result["description"] == "Async new description"

        stored = knowledge.contents_db.get_knowledge_content("async-missing-id")  # type: ignore[union-attr]
        assert stored is not None
        assert stored.name == "Async new name"  # type: ignore[union-attr]

    async def test_existing_row_is_updated_in_place(self, tmp_path):
        knowledge = _make_knowledge(tmp_path)

        await knowledge._aupdate_content(
            Content(
                id="async-existing-id",
                name="Original async",
                description="Original async",
            )
        )
        result = await knowledge._aupdate_content(
            Content(
                id="async-existing-id",
                name="Updated async",
                description="Updated async",
            )
        )

        assert result is not None
        assert result["name"] == "Updated async"

        stored = knowledge.contents_db.get_knowledge_content("async-existing-id")  # type: ignore[union-attr]
        assert stored is not None
        assert stored.name == "Updated async"  # type: ignore[union-attr]
