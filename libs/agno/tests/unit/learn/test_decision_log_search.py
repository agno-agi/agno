"""Unit tests for DecisionLogStore search routing through search_learnings."""

import logging
from typing import Any, Dict, List

import pytest

from agno.db.base import BaseDb
from agno.learn.config import DecisionLogConfig
from agno.learn.schemas import DecisionLog
from agno.learn.stores.decision_log import DecisionLogStore


class FakeDecisionDb(BaseDb):
    """Subclasses BaseDb (the sync search path requires a real BaseDb) but
    only implements what DecisionLogStore touches."""

    def __init__(self) -> None:  # noqa: D401 - do not call BaseDb.__init__
        self.rows: List[Dict[str, Any]] = []
        self.search_calls: List[Dict[str, Any]] = []

    # --- what the store uses ---
    def upsert_learning(self, id: str, **kwargs: Any) -> None:
        self.rows.append({"learning_id": id, **kwargs})

    def get_learnings(self, **kwargs: Any) -> List[Dict[str, Any]]:
        limit = kwargs.get("limit")
        rows = list(reversed(self.rows))
        return rows[:limit] if limit else rows

    def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        import json

        self.search_calls.append({"query": query, **kwargs})
        rows = [row for row in reversed(self.rows) if query.lower() in json.dumps(row.get("content", {})).lower()]
        limit = kwargs.get("limit")
        return rows[:limit] if limit else rows

    # --- abstract surface stubs ---
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)


# BaseDb is an ABC with many abstract methods; bypass instantiation checks.
FakeDecisionDb.__abstractmethods__ = frozenset()


def _store(db: FakeDecisionDb) -> DecisionLogStore:
    return DecisionLogStore(config=DecisionLogConfig(db=db))


def _log(store: DecisionLogStore, decision: str, decision_type: str = "tool_selection") -> None:
    import uuid

    store.save(decision=DecisionLog(id=f"dec_{uuid.uuid4().hex[:6]}", decision=decision, decision_type=decision_type))


def test_query_routes_through_search_learnings() -> None:
    db = FakeDecisionDb()
    store = _store(db)
    _log(store, "Chose Postgres over Dynamo")
    _log(store, "Used web search for news")

    results = store.search(query="postgres")
    assert len(results) == 1
    assert results[0].decision == "Chose Postgres over Dynamo"
    assert db.search_calls and db.search_calls[0]["learning_type"] == "decision_log"


def test_no_query_uses_listing_path() -> None:
    db = FakeDecisionDb()
    store = _store(db)
    _log(store, "first")
    _log(store, "second")

    results = store.search()
    assert len(results) == 2
    assert db.search_calls == []


def test_fallback_on_not_implemented_filters_client_side(caplog: pytest.LogCaptureFixture) -> None:
    class NoSearchDb(FakeDecisionDb):
        def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
            raise NotImplementedError

    NoSearchDb.__abstractmethods__ = frozenset()
    db = NoSearchDb()
    store = _store(db)
    _log(store, "Chose Postgres over Dynamo")
    _log(store, "Used web search for news")

    with caplog.at_level(logging.WARNING):
        results = store.search(query="postgres")
        store.search(query="postgres")

    assert len(results) == 1
    assert results[0].decision == "Chose Postgres over Dynamo"
    degraded = [r for r in caplog.records if "no search_learnings implementation" in r.getMessage()]
    assert len(degraded) == 1


async def test_async_query_routes_through_search_learnings() -> None:
    db = FakeDecisionDb()
    store = _store(db)
    _log(store, "Chose Postgres over Dynamo")

    results = await store.asearch(query="postgres", session_id="sess-9")
    assert len(results) == 1
    assert db.search_calls and db.search_calls[0]["query"] == "postgres"
    # The sync-db branch of asearch honors session_id too
    assert db.search_calls[0]["session_id"] == "sess-9"


def test_server_hit_in_any_field_is_kept() -> None:
    # A hit whose only match is in a field to_text() omits (alternatives) must
    # survive the client-side value verification.
    import uuid

    db = FakeDecisionDb()
    store = _store(db)
    store.save(
        decision=DecisionLog(
            id=f"dec_{uuid.uuid4().hex[:6]}",
            decision="Picked the database",
            alternatives=["postgres", "dynamo"],
        )
    )

    results = store.search(query="postgres")
    assert len(results) == 1
    assert db.search_calls  # served by the server-side path, kept by the verifier


def test_json_key_names_do_not_match_decisions() -> None:
    db = FakeDecisionDb()
    store = _store(db)
    _log(store, "Chose Postgres over Dynamo")

    assert store.search(query="reasoning") == []
    assert store.search(query="decision_type") == []


def test_decision_log_defaults_agentic_and_never_writes_contentless_rows() -> None:
    from agno.learn.config import LearningMode

    assert DecisionLogConfig().mode is LearningMode.AGENTIC

    db = FakeDecisionDb()
    store = _store(db)

    # The old ALWAYS extraction wrote one contentless row per tool call from
    # the message snapshot; process is now a no-op.
    class FakeToolCallMessage:
        tool_calls = [type("TC", (), {"name": "web_search"})()]

    store.process(messages=[FakeToolCallMessage()], agent_id="a1", session_id="s1")
    assert db.rows == []
    assert not hasattr(store, "_extract_decisions_from_messages")


def test_search_honors_session_id() -> None:
    db = FakeDecisionDb()
    captured: List[Dict[str, Any]] = []
    original = db.search_learnings

    def spy(query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        captured.append(kwargs)
        return original(query, **kwargs)

    db.search_learnings = spy  # type: ignore[method-assign]
    store = _store(db)
    _log(store, "Chose Postgres over Dynamo")

    store.search(query="postgres", session_id="sess-42")
    assert captured and captured[0]["session_id"] == "sess-42"

    # And the listing path passes it to get_learnings
    listing_calls: List[Dict[str, Any]] = []
    original_get = db.get_learnings

    def spy_get(**kwargs: Any) -> List[Dict[str, Any]]:
        listing_calls.append(kwargs)
        return original_get(**kwargs)

    db.get_learnings = spy_get  # type: ignore[method-assign]
    store.search(session_id="sess-42")
    assert listing_calls and listing_calls[0]["session_id"] == "sess-42"


def test_decision_type_filter_composes_with_query() -> None:
    db = FakeDecisionDb()
    store = _store(db)
    _log(store, "Chose Postgres over Dynamo", decision_type="architecture")
    _log(store, "Postgres connection retry", decision_type="tool_selection")

    results = store.search(query="postgres", decision_type="architecture")
    assert len(results) == 1
    assert results[0].decision_type == "architecture"


def test_query_variants_keeps_the_query_itself() -> None:
    """A mixed-separator query has no uniform-separator form.

    The db matches "end-to-end tests" through the LIKE single-char wildcard;
    a verifier that only knows "end to end tests" and "end_to_end_tests"
    discards that hit and the store answers "No entities matching".
    """
    from agno.learn.utils import query_variants

    assert "end-to-end tests" in query_variants("end-to-end tests")
    assert "user_id column" in query_variants("user_id column")
    # the separator-swapped forms are still generated
    assert "end_to_end_tests" in query_variants("end-to-end tests")
    assert "sarah_chen" in query_variants("sarah chen")
    assert query_variants("   ") == []


def test_search_patterns_wildcard_non_ascii_escapes() -> None:
    """SQLite compares the JSON escape as literal text and LIKE folds ASCII
    only, so no pre-cased whole-string variant reaches a mixed form like "Ος".
    The escape carries a wildcard per character instead; the caller's
    value-scoped Python check casefolds and rejects the slack.
    """
    from agno.db.utils import learning_search_patterns

    patterns = learning_search_patterns("Ος")
    assert any("______" in p for p in patterns), patterns
    # the raw form is still offered, for Postgres where ::text is real characters
    assert any("Ος" in p for p in patterns), patterns
    # ASCII queries gain no wildcard padding
    assert all("______" not in p for p in learning_search_patterns("sarah chen"))


def test_value_projection_and_variants_casefold() -> None:
    from agno.learn.utils import content_values_text, query_variants

    assert content_values_text({"facts": ["Ος"]}) == query_variants("ΟΣ")[0]
    assert query_variants("CAFÉ")[0] == "café"


def test_recall_is_not_scoped_to_the_current_session(tmp_path) -> None:
    """A decision log's value is cross-session.

    recall() receives the run's session_id from LearningMachine, and forwarding
    it into search() made the injected block say "No recent decisions logged" to
    every new session while the store was full. search(session_id=...) still
    scopes for explicit callers.
    """
    from agno.db.sqlite import SqliteDb
    from agno.learn.config import DecisionLogConfig, LearningMode
    from agno.learn.stores.decision_log import DecisionLogStore

    store = DecisionLogStore(
        config=DecisionLogConfig(db=SqliteDb(db_file=str(tmp_path / "d.db")), mode=LearningMode.AGENTIC)
    )
    log_decision = next(
        t for t in store.get_tools(agent_id="a1", session_id="session-one") if t.__name__ == "log_decision"
    )
    log_decision(decision="Postgres over Dynamo", reasoning="advisory locks")

    from_another_session = store.recall(agent_id="a1", session_id="session-two")
    assert from_another_session and from_another_session[0].decision == "Postgres over Dynamo"

    assert store.search(agent_id="a1", session_id="session-two") == []
    assert len(store.search(agent_id="a1", session_id="session-one")) == 1
