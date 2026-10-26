"""
Unit tests for the ``topics`` query parameter in GET /memories.

``parse_topics`` declares ``Optional[List[str]]``, so FastAPI collects a repeated
query parameter into one element per occurrence. Reading only ``topics[0]``
silently dropped every occurrence after the first, narrowing the filter without
any error -- the caller got a result set they did not ask for.

Uses FastAPI TestClient to exercise the real ASGI stack end-to-end, and asserts
on the value handed to the DB layer rather than on the response body.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_async_db():
    """Create an AsyncBaseDb mock that passes isinstance checks."""
    from agno.db.base import AsyncBaseDb

    mock = MagicMock(spec=AsyncBaseDb)
    mock.id = "test-db"
    # get_user_memories returns (list[dict], int)
    mock.get_user_memories = AsyncMock(return_value=([], 0))
    return mock


def _build_app_with_memory_router(db):
    from agno.os.routers.memory import get_memory_router
    from agno.os.settings import AgnoAPISettings

    app = FastAPI()
    router = get_memory_router(dbs={"test-db": [db]}, settings=AgnoAPISettings())
    app.include_router(router)
    return app


class TestMemoryTopicsFilter:
    """Test the topics parameter in GET /memories."""

    @pytest.fixture
    def db(self):
        return _make_async_db()

    @pytest.fixture
    def client(self, db):
        return TestClient(_build_app_with_memory_router(db))

    def _topics_passed_to_db(self, client, db, query):
        response = client.get(f"/memories?db_id=test-db{query}")
        assert response.status_code == 200, response.text
        db.get_user_memories.assert_called_once()
        return db.get_user_memories.call_args.kwargs["topics"]

    def test_repeated_query_parameter_keeps_every_occurrence(self, client, db):
        """``?topics=a&topics=b`` is the standard spelling for a list parameter.

        Only the first occurrence used to survive, so a caller filtering on three
        topics silently got a filter on one.
        """
        assert self._topics_passed_to_db(client, db, "&topics=preferences&topics=technical") == [
            "preferences",
            "technical",
        ]

    def test_three_repeated_occurrences(self, client, db):
        assert self._topics_passed_to_db(client, db, "&topics=a&topics=b&topics=c") == ["a", "b", "c"]

    def test_comma_separated_value_still_works(self, client, db):
        """The documented spelling is unchanged."""
        assert self._topics_passed_to_db(client, db, "&topics=preferences,technical") == [
            "preferences",
            "technical",
        ]

    def test_mixed_comma_and_repeated_spellings(self, client, db):
        """Nothing forces a caller to pick one spelling, so both compose."""
        assert self._topics_passed_to_db(client, db, "&topics=a,b&topics=c") == ["a", "b", "c"]

    def test_whitespace_is_stripped_in_every_occurrence(self, client, db):
        """Stripping applied to the first occurrence only; now it applies to all."""
        assert self._topics_passed_to_db(client, db, "&topics=%20a%20,%20b%20&topics=%20c%20") == ["a", "b", "c"]

    def test_omitted_topics_is_none(self, client, db):
        """No filter at all must stay ``None``, not an empty list."""
        assert self._topics_passed_to_db(client, db, "") is None

    def test_empty_value_yields_empty_list(self, client, db):
        """``?topics=`` names no topic. Pre-existing behaviour, kept deliberately."""
        assert self._topics_passed_to_db(client, db, "&topics=") == []

    def test_bare_comma_yields_empty_list(self, client, db):
        """``?topics=,`` splits into two empty strings, both dropped."""
        assert self._topics_passed_to_db(client, db, "&topics=,") == []

    def test_empty_occurrence_among_real_ones_is_dropped(self, client, db):
        assert self._topics_passed_to_db(client, db, "&topics=a&topics=") == ["a"]
