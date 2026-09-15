"""Ticket 16: Oracle/AsyncOracleDb dispatch across all four migration-version
modules never falls through to the generic "not implemented" / "NoSQL/document
store" branch -- it hits an explicit, decided branch instead.

Oracle's schema was built directly against the v3.0.0 target shape (this
effort's own tickets 02+); no pre-3.0.0 Oracle table has ever existed. Each
migration's Oracle branch is therefore a documented no-op, verified against
``agno.db.oracle.schemas`` column-by-column before being written (see each
version module's own comment). These tests pin the DECISION -- an explicit,
correctly-worded no-op -- not just the return value, since a silent fallback
also returns False and would pass a return-value-only test.
"""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("sqlalchemy")

from agno.db.migrations.versions import v2_3_0, v2_5_0, v2_5_6, v3_0_0  # noqa: E402


def _make_db(class_name: str):
    """A fake db instance whose type().__name__ is class_name, matching the
    dispatch pattern test_migration_v2_5_0_dispatch.py already established.
    """
    mock = MagicMock()

    class FakeDb:
        def __getattr__(self, name):
            return getattr(mock, name)

    FakeDb.__name__ = class_name
    FakeDb.__qualname__ = class_name
    return FakeDb()


NOT_IMPLEMENTED_PHRASES = ("not implemented", "nosql/document store")


def _assert_no_fallback_phrase(caplog):
    lowered = caplog.text.lower()
    for phrase in NOT_IMPLEMENTED_PHRASES:
        assert phrase not in lowered, (
            f"Oracle dispatch fell through to the generic fallback ({phrase!r}): {caplog.text}"
        )


class TestV2_3_0OracleDispatch:
    def test_up_is_explicit_no_op(self, caplog):
        with caplog.at_level("INFO"):
            assert v2_3_0.up(_make_db("OracleDb"), "memories", "agno_memories") is False
        assert "already present since table creation" in caplog.text
        _assert_no_fallback_phrase(caplog)

    @pytest.mark.asyncio
    async def test_async_up_is_explicit_no_op(self, caplog):
        with caplog.at_level("INFO"):
            assert await v2_3_0.async_up(_make_db("AsyncOracleDb"), "memories", "agno_memories") is False
        assert "already present since table creation" in caplog.text
        _assert_no_fallback_phrase(caplog)

    def test_down_is_explicit_no_op(self, caplog):
        with caplog.at_level("INFO"):
            assert v2_3_0.down(_make_db("OracleDb"), "memories", "agno_memories") is False
        assert "no pre-v2.3.0 oracle schema exists" in caplog.text.lower()
        _assert_no_fallback_phrase(caplog)

    @pytest.mark.asyncio
    async def test_async_down_is_explicit_no_op(self, caplog):
        with caplog.at_level("INFO"):
            assert await v2_3_0.async_down(_make_db("AsyncOracleDb"), "memories", "agno_memories") is False
        assert "no pre-v2.3.0 oracle schema exists" in caplog.text.lower()
        _assert_no_fallback_phrase(caplog)


class TestV2_5_0OracleDispatch:
    def test_up_is_explicit_no_op(self):
        # v2.5.0's fallback message is identical for the SqliteDb branch and
        # the generic else, so this pins behavior (False, no exception) --
        # the module-level comment records the decision.
        assert v2_5_0.up(_make_db("OracleDb"), "sessions", "agno_sessions") is False

    @pytest.mark.asyncio
    async def test_async_up_is_explicit_no_op(self):
        assert await v2_5_0.async_up(_make_db("AsyncOracleDb"), "sessions", "agno_sessions") is False

    def test_down_is_explicit_no_op(self):
        assert v2_5_0.down(_make_db("OracleDb"), "sessions", "agno_sessions") is False

    @pytest.mark.asyncio
    async def test_async_down_is_explicit_no_op(self):
        assert await v2_5_0.async_down(_make_db("AsyncOracleDb"), "sessions", "agno_sessions") is False


class TestV2_5_6OracleDispatch:
    def test_up_is_explicit_no_op(self):
        assert v2_5_6.up(_make_db("OracleDb"), "approvals", "agno_approvals") is False

    @pytest.mark.asyncio
    async def test_async_up_is_explicit_no_op(self):
        assert await v2_5_6.async_up(_make_db("AsyncOracleDb"), "approvals", "agno_approvals") is False

    def test_down_is_explicit_no_op(self):
        assert v2_5_6.down(_make_db("OracleDb"), "approvals", "agno_approvals") is False

    @pytest.mark.asyncio
    async def test_async_down_is_explicit_no_op(self):
        assert await v2_5_6.async_down(_make_db("AsyncOracleDb"), "approvals", "agno_approvals") is False


class TestV3_0_0OracleDispatch:
    def test_up_is_explicit_no_op(self, caplog):
        with caplog.at_level("INFO"):
            assert v3_0_0.up(_make_db("OracleDb"), "sessions", "agno_sessions") is False
        assert "already present since table creation" in caplog.text
        _assert_no_fallback_phrase(caplog)

    @pytest.mark.asyncio
    async def test_async_up_is_explicit_no_op(self, caplog):
        with caplog.at_level("INFO"):
            assert await v3_0_0.async_up(_make_db("AsyncOracleDb"), "sessions", "agno_sessions") is False
        assert "already present since table creation" in caplog.text
        _assert_no_fallback_phrase(caplog)

    def test_down_is_explicit_no_op(self, caplog):
        with caplog.at_level("INFO"):
            assert v3_0_0.down(_make_db("OracleDb"), "sessions", "agno_sessions") is False
        assert "no pre-v3.0.0 oracle schema exists" in caplog.text.lower()
        _assert_no_fallback_phrase(caplog)

    @pytest.mark.asyncio
    async def test_async_down_is_explicit_no_op(self, caplog):
        with caplog.at_level("INFO"):
            assert await v3_0_0.async_down(_make_db("AsyncOracleDb"), "sessions", "agno_sessions") is False
        assert "no pre-v3.0.0 oracle schema exists" in caplog.text.lower()
        _assert_no_fallback_phrase(caplog)

    def test_learnings_content_rekey_takes_real_path_not_oracle_branch(self, monkeypatch):
        """The learnings rekey dispatches on table_type, before the db_type
        check -- it must reach _rekey_learnings even for OracleDb, never the
        Oracle no-op branch (which would silently skip a real content move).
        """
        called = {}

        def _fake_rekey(db, table_name):
            called["hit"] = True
            return True

        monkeypatch.setattr(v3_0_0, "_rekey_learnings", _fake_rekey)
        result = v3_0_0.up(_make_db("OracleDb"), "learnings", "agno_learnings")
        assert called.get("hit") is True
        assert result is True

    @pytest.mark.asyncio
    async def test_async_learnings_content_rekey_takes_real_path(self, monkeypatch):
        called = {}

        async def _fake_arekey(db, table_name):
            called["hit"] = True
            return True

        monkeypatch.setattr(v3_0_0, "_arekey_learnings", _fake_arekey)
        result = await v3_0_0.async_up(_make_db("AsyncOracleDb"), "learnings", "agno_learnings")
        assert called.get("hit") is True
        assert result is True
