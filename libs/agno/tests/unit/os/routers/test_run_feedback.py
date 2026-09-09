"""Tests for the run feedback endpoints on the session router."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.routers.session.session import get_session_router
from agno.os.settings import AgnoAPISettings
from agno.remote.base import RemoteDb


def _make_session(**overrides):
    d = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "runs": [
            {
                "run_id": "run-1",
                "agent_id": "agent-1",
                "input": {"input_content": "What is the population of Tokyo?"},
                "content": "Tokyo has about 14 million residents.",
            }
        ],
    }
    d.update(overrides)
    return d


def _make_feedback_record(**overrides):
    d = {
        "id": "feedback_run-1",
        "learning_type": "feedback",
        "session_id": "sess-1",
        "user_id": "user-1",
        "agent_id": "agent-1",
        "content": {
            "id": "feedback_run-1",
            "signal": "negative",
            "comment": "too verbose",
            "run_id": "run-1",
            "session_id": "sess-1",
            "user_id": "user-1",
            "agent_id": "agent-1",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    }
    d.update(overrides)
    return d


@pytest.fixture
def mock_db():
    db = MagicMock(spec=BaseDb)
    db.get_session = MagicMock(return_value=_make_session())
    db.get_learning_by_id = MagicMock(return_value=None)
    db.upsert_learning = MagicMock(return_value=None)
    db.delete_learning = MagicMock(return_value=True)
    return db


def _make_client(db) -> TestClient:
    app = FastAPI()
    router = get_session_router(dbs={"default": [db]}, settings=AgnoAPISettings())
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def client(mock_db):
    return _make_client(mock_db)


@pytest.fixture
def scoped_client(mock_db):
    """Client for a scoped (non-admin) JWT caller with user isolation enabled."""
    app = FastAPI()

    @app.middleware("http")
    async def add_jwt_user(request, call_next):
        request.state.user_isolation_enabled = True
        request.state.user_id = "user-1"
        request.state.scopes = []
        return await call_next(request)

    router = get_session_router(dbs={"default": [mock_db]}, settings=AgnoAPISettings())
    app.include_router(router)
    return TestClient(app)


class TestCreateRunFeedback:
    def test_create(self, client, mock_db):
        resp = client.post(
            "/sessions/sess-1/runs/run-1/feedback",
            json={"signal": "negative", "comment": "too verbose"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["feedback_id"] == "feedback_run-1"
        assert body["signal"] == "negative"
        assert body["comment"] == "too verbose"
        assert body["run_id"] == "run-1"
        assert body["agent_id"] == "agent-1"
        assert body["created_at"] is not None

        kwargs = mock_db.upsert_learning.call_args[1]
        assert kwargs["id"] == "feedback_run-1"
        assert kwargs["learning_type"] == "feedback"
        assert kwargs["session_id"] == "sess-1"
        assert kwargs["content"]["context"].startswith("User input: What is the population")

        # The endpoint stores the raw comment; distillation only happens via
        # FeedbackStore.record(), so learning is always None here.
        assert body["learning"] is None
        assert kwargs["content"]["learning"] is None

    def test_re_review_preserves_created_at(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record())
        resp = client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "positive"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["signal"] == "positive"
        assert body["created_at"] == "2026-01-01T00:00:00+00:00"
        assert body["updated_at"] is not None

    def test_re_review_reports_the_scope_the_row_actually_has(self, client, mock_db):
        # A re-review cannot move the scope columns, and recall() reads them: reporting
        # the run's agent would name one the row is not filed under.
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(session_id=None, agent_id=None))
        resp = client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "positive"})
        assert resp.status_code == 201
        assert resp.json()["agent_id"] is None
        assert mock_db.upsert_learning.call_args[1]["content"]["agent_id"] is None
        assert mock_db.upsert_learning.call_args[1]["content"]["session_id"] is None

    def test_session_not_found(self, client, mock_db):
        mock_db.get_session = MagicMock(return_value=None)
        resp = client.post("/sessions/missing/runs/run-1/feedback", json={"signal": "positive"})
        assert resp.status_code == 404

    def test_run_not_found(self, client):
        resp = client.post("/sessions/sess-1/runs/missing/feedback", json={"signal": "positive"})
        assert resp.status_code == 404

    def test_invalid_signal(self, client):
        resp = client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "meh"})
        assert resp.status_code == 422


class TestGetRunFeedback:
    def test_get(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record())
        resp = client.get("/sessions/sess-1/runs/run-1/feedback")
        assert resp.status_code == 200
        body = resp.json()
        assert body["feedback_id"] == "feedback_run-1"
        assert body["signal"] == "negative"

    def test_not_found(self, client):
        resp = client.get("/sessions/sess-1/runs/run-1/feedback")
        assert resp.status_code == 404

    def test_session_mismatch_is_not_found(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(session_id="other-session"))
        resp = client.get("/sessions/sess-1/runs/run-1/feedback")
        assert resp.status_code == 404

    def test_null_session_column_is_not_a_mismatch(self, client, mock_db):
        # The scope columns are written on insert only, so a row recorded without a
        # session keeps a null one -- reading that as a mismatch made it unreachable.
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(session_id=None))
        resp = client.get("/sessions/sess-1/runs/run-1/feedback")
        assert resp.status_code == 200
        assert resp.json()["feedback_id"] == "feedback_run-1"


class TestDeleteRunFeedback:
    def test_delete(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record())
        resp = client.delete("/sessions/sess-1/runs/run-1/feedback")
        assert resp.status_code == 204
        mock_db.delete_learning.assert_called_once_with("feedback_run-1")

    def test_not_found(self, client, mock_db):
        resp = client.delete("/sessions/sess-1/runs/run-1/feedback")
        assert resp.status_code == 404
        mock_db.delete_learning.assert_not_called()

    def test_null_session_column_is_deletable(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(session_id=None))
        resp = client.delete("/sessions/sess-1/runs/run-1/feedback")
        assert resp.status_code == 204
        mock_db.delete_learning.assert_called_once_with("feedback_run-1")


class TestTeamRunFeedback:
    def test_create_captures_team_id(self, client, mock_db):
        team_session = _make_session(
            runs=[{"run_id": "run-1", "team_id": "team-1", "content": "Team answer."}],
        )
        mock_db.get_session = MagicMock(return_value=team_session)
        resp = client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "negative"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["team_id"] == "team-1"
        assert body["agent_id"] is None

        kwargs = mock_db.upsert_learning.call_args[1]
        assert kwargs["team_id"] == "team-1"
        assert kwargs["agent_id"] is None


class TestRunFeedbackContext:
    def test_context_is_returned_on_the_owner_scoped_route(self, client, mock_db):
        # The exchange is not injected into anyone's prompt any more, so this route --
        # which 404s a cross-user caller -- is where a UI reads back what it reviewed.
        resp = client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "negative"})
        assert resp.status_code == 201
        assert resp.json()["context"] is not None
        assert resp.json()["context"] == mock_db.upsert_learning.call_args[1]["content"]["context"]

    def test_created_at_is_backfilled_when_the_stored_row_lost_it(self, client, mock_db):
        record = _make_feedback_record()
        record["content"].pop("created_at", None)
        mock_db.get_learning_by_id = MagicMock(return_value=record)

        resp = client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "positive"})
        assert resp.status_code == 201
        assert resp.json()["created_at"] is not None


class TestFeedbackScoping:
    """Mirrors the learnings router's _enforce_user_scope contract for the same table:
    a scoped (non-admin) caller reads shared (no-owner) feedback but cannot mutate it,
    and feedback owned by a different user 404s to leak nothing."""

    def test_scoped_read_of_shared_feedback_allowed(self, scoped_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(user_id=None))
        resp = scoped_client.get("/sessions/sess-1/runs/run-1/feedback")
        assert resp.status_code == 200

    def test_scoped_delete_of_shared_feedback_rejected(self, scoped_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(user_id=None))
        resp = scoped_client.delete("/sessions/sess-1/runs/run-1/feedback")
        assert resp.status_code == 403
        mock_db.delete_learning.assert_not_called()

    def test_scoped_overwrite_of_shared_feedback_rejected(self, scoped_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(user_id=None))
        resp = scoped_client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "positive"})
        assert resp.status_code == 403
        mock_db.upsert_learning.assert_not_called()

    def test_scoped_cross_user_feedback_is_not_found(self, scoped_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(user_id="user-2"))
        assert scoped_client.get("/sessions/sess-1/runs/run-1/feedback").status_code == 404
        assert scoped_client.delete("/sessions/sess-1/runs/run-1/feedback").status_code == 404
        mock_db.delete_learning.assert_not_called()

    def test_scoped_owner_match_coerces_non_string_ids(self, scoped_client, mock_db):
        # Only the SQL adapters type the user_id column, so the owner can come back as an
        # int against a string JWT subject -- same_user() is what makes 1 and "1" match.
        app = FastAPI()

        @app.middleware("http")
        async def add_jwt_user(request, call_next):
            request.state.user_isolation_enabled = True
            request.state.user_id = "1"
            request.state.scopes = []
            return await call_next(request)

        router = get_session_router(dbs={"default": [mock_db]}, settings=AgnoAPISettings())
        app.include_router(router)
        numeric_client = TestClient(app)

        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(user_id=1))
        assert numeric_client.get("/sessions/sess-1/runs/run-1/feedback").status_code == 200
        assert numeric_client.delete("/sessions/sess-1/runs/run-1/feedback").status_code == 204

    def test_scoped_caller_mutates_own_feedback(self, scoped_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record(user_id="user-1"))
        assert (
            scoped_client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "positive"}).status_code == 201
        )
        assert scoped_client.delete("/sessions/sess-1/runs/run-1/feedback").status_code == 204


class TestRunFeedbackErrorBranches:
    def test_upsert_not_implemented_returns_501(self, client, mock_db):
        mock_db.upsert_learning.side_effect = NotImplementedError
        resp = client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "positive"})
        assert resp.status_code == 501

    def test_upsert_db_error_returns_500(self, client, mock_db):
        mock_db.upsert_learning.side_effect = RuntimeError("boom")
        resp = client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "positive"})
        assert resp.status_code == 500

    def test_get_db_error_returns_500(self, client, mock_db):
        mock_db.get_learning_by_id.side_effect = RuntimeError("boom")
        assert client.get("/sessions/sess-1/runs/run-1/feedback").status_code == 500

    def test_delete_db_error_returns_500(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_feedback_record())
        mock_db.delete_learning.side_effect = RuntimeError("boom")
        assert client.delete("/sessions/sess-1/runs/run-1/feedback").status_code == 500

    def test_remote_db_returns_501(self):
        client = _make_client(MagicMock(spec=RemoteDb))
        assert client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "positive"}).status_code == 501
        assert client.get("/sessions/sess-1/runs/run-1/feedback").status_code == 501
        assert client.delete("/sessions/sess-1/runs/run-1/feedback").status_code == 501


class TestAsyncDbRunFeedback:
    @pytest.fixture
    def async_db(self):
        db = MagicMock(spec=AsyncBaseDb)
        db.get_session = AsyncMock(return_value=_make_session())
        db.get_learning_by_id = AsyncMock(return_value=None)
        db.upsert_learning = AsyncMock(return_value=None)
        db.delete_learning = AsyncMock(return_value=True)
        return db

    def test_create(self, async_db):
        client = _make_client(async_db)
        resp = client.post("/sessions/sess-1/runs/run-1/feedback", json={"signal": "negative", "comment": "hm"})
        assert resp.status_code == 201
        kwargs = async_db.upsert_learning.call_args[1]
        assert kwargs["id"] == "feedback_run-1"
        assert kwargs["learning_type"] == "feedback"

    def test_get_and_delete(self, async_db):
        async_db.get_learning_by_id = AsyncMock(return_value=_make_feedback_record())
        client = _make_client(async_db)
        assert client.get("/sessions/sess-1/runs/run-1/feedback").status_code == 200
        assert client.delete("/sessions/sess-1/runs/run-1/feedback").status_code == 204
        async_db.delete_learning.assert_awaited_once_with("feedback_run-1")
