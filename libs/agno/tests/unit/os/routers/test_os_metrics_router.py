"""Tests for the GET /os/metrics/* routes on the metrics router."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.client import AgentOSClient
from agno.db.mongo import MongoDb
from agno.db.sqlite import SqliteDb
from agno.db.utils import merge_metrics_totals
from agno.os import AgentOS, Authorization
from agno.os.routers.metrics.metrics import get_metrics_router
from agno.os.settings import AgnoAPISettings
from agno.remote.base import RemoteDb

# =============================================================================
# Fixtures
# =============================================================================

# The second the database last wrote the rows of every window, as the mock reports it
UPDATED_AT = 1_800_000_000
UPDATED_AT_ISO = "2027-01-15T08:00:00Z"

KEPT_ROUTES = ("sessions", "tokens", "runs", "latency", "models")

SECRET = "users-metrics-secret-at-least-256-bits-long"
OS_ID = "users-os"


def _today():
    return datetime.now(timezone.utc).date()


def _last(days):
    """Query string for the window of the last ``days`` days, ending today."""
    start = _today() - timedelta(days=days - 1)
    return f"starting_date={start.isoformat()}"


def _day(days_ago):
    return _today() - timedelta(days=days_ago)


def _iso(day):
    return f"{day.isoformat()}T00:00:00Z"


def _row(day, **fields):
    """One day's totals as get_component_metrics returns them, keyed by the field names a route asks for."""
    return {"date": day, **fields}


def _totals(*rows):
    """Answer each get_component_metrics read with the requested fields of the rows inside its window."""

    def read(*args, **kwargs):
        starting_date, ending_date = kwargs["starting_date"], kwargs["ending_date"]
        inside = [row for row in rows if starting_date <= row["date"] <= ending_date]
        fields = kwargs["fields"]
        return [
            {"date": row["date"], **{field: row[field] for field in fields if field in row}}
            for row in sorted(inside, key=lambda row: row["date"])
        ], UPDATED_AT

    return read


def _window_totals(*rows):
    """Answer each get_metrics_totals read with the requested fields of the rows inside its window, as one total."""

    def read(*args, **kwargs):
        totals, updated_at = _totals(*rows)(*args, **kwargs)
        fields = kwargs["fields"]
        window_totals = merge_metrics_totals(totals, [field for field in fields if field != "model_metrics"])
        if "model_metrics" in fields:
            window_totals["model_metrics"] = [model for day in totals for model in day.get("model_metrics", [])]
        return window_totals, updated_at if totals else None

    return read


def _today_row():
    """Today: 3 sessions, 4 runs no other run started of which 3 completed, 300 tokens, two models."""
    return _row(
        _day(0),
        sessions_count=3,
        root_runs_count=4,
        status_metrics={"COMPLETED": 3, "ERROR": 1},
        total_tokens=300,
        duration_runs_count=3,
        total_duration_ms=6000,
        max_duration_ms=4000,
        time_to_first_token_runs_count=3,
        total_time_to_first_token_ms=1500,
        max_time_to_first_token_ms=800,
        model_calls_count=4,
        total_model_call_ms=4000,
        max_model_call_ms=2000,
        duration_buckets={"le_1000": 1, "le_2500": 1, "le_4000": 1},
        time_to_first_token_buckets={"le_1000": 3},
        model_call_buckets={"le_1000": 4},
        model_metrics=[
            {"model_id": "claude-opus-5", "model_provider": "Anthropic", "count": 1},
            {"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": 3},
        ],
    )


def _yesterday_row():
    """Yesterday: 1 session, 1 cancelled run and 1 completed run that was timed, 100 tokens."""
    return _row(
        _day(1),
        sessions_count=1,
        root_runs_count=2,
        status_metrics={"CANCELLED": 1, "COMPLETED": 1},
        total_tokens=100,
        duration_runs_count=1,
        total_duration_ms=1000,
        max_duration_ms=1000,
        time_to_first_token_runs_count=1,
        total_time_to_first_token_ms=300,
        max_time_to_first_token_ms=300,
        model_calls_count=1,
        total_model_call_ms=500,
        max_model_call_ms=500,
        duration_buckets={"le_1000": 1},
        time_to_first_token_buckets={"le_300": 1},
        model_call_buckets={"le_500": 1},
        model_metrics=[{"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": 1}],
    )


def _three_days_ago_row():
    """Three days ago: 4 sessions, 2 completed runs, 400 tokens, nothing timed."""
    return _row(
        _day(3),
        sessions_count=4,
        root_runs_count=2,
        status_metrics={"COMPLETED": 2},
        total_tokens=400,
        model_metrics=[],
    )


def _db(db_id, *rows):
    """A database with the given id that answers both reads from the given rows."""
    db = MagicMock()
    db.id = db_id
    db.db_engine = None
    db.user_metrics_table_name = "agno_user_metrics"
    db.get_component_metrics = MagicMock(side_effect=_totals(*rows))
    db.get_metrics_totals = MagicMock(side_effect=_window_totals(*rows))
    return db


def _versions():
    """What get_metrics_versions reports: the version of today's and yesterday's everyone rows."""
    return {f"daily {_day(0).isoformat()}": 1, f"daily {_day(1).isoformat()}": 1}


@pytest.fixture
def settings():
    return AgnoAPISettings()


@pytest.fixture
def mock_db():
    """Rows for today, yesterday and three days ago, so a two-day window has the two days before it to compare with."""
    return _db("db-1", _today_row(), _yesterday_row(), _three_days_ago_row())


def _client(settings, os_db, *other_dbs):
    """A test client of the metrics router with auth off, for an AgentOS with the given databases, the first its own."""
    app = FastAPI()
    with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
        app.include_router(
            get_metrics_router(dbs={db.id: [db] for db in (os_db, *other_dbs)}, settings=settings, os_db=os_db)
        )
    return TestClient(app)


@pytest.fixture
def client(mock_db, settings):
    return _client(settings, mock_db)


def _users_client(dbs, user_store=None, require_admin=None):
    """A test client of the metrics router with auth off and the admin gate passed, unless another is given, for an
    AgentOS with the given databases and user directory."""
    app = FastAPI()
    if user_store is not None:
        app.state.user_store = user_store
    with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
        with patch(
            "agno.os.routers.metrics.metrics._make_require_admin",
            return_value=require_admin or AsyncMock(return_value=""),
        ):
            app.include_router(get_metrics_router(dbs=dbs, settings=AgnoAPISettings()))
    return TestClient(app)


def _remote_db(db_id, remote_client):
    """A RemoteDb with the given id, on a remote AgentOS that answers every read through the given test client."""
    agentos_client = AgentOSClient(base_url="http://remote-os")

    async def remote_get(endpoint, params=None, headers=None):
        return remote_client.get(endpoint, params=params, headers=headers).json()

    agentos_client._aget = AsyncMock(side_effect=remote_get)  # type: ignore[method-assign]
    return RemoteDb(id=db_id, client=agentos_client)


def _created_row(days_ago, count):
    """A row of the directory's users-created-per-day read, keyed by the day's start in epoch seconds."""
    day = _today() - timedelta(days=days_ago)
    return {"date": int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()), "count": count}


def _created_by_day(*rows):
    """Answer each directory read with the rows created before the bound it asks for."""

    async def read(starting_at=None, ending_before=None):
        return [row for row in rows if ending_before is None or row["date"] < ending_before]

    return read


def _token(sub: str, **claims) -> str:
    payload = {
        "sub": sub,
        "aud": OS_ID,
        "scopes": claims.pop("scopes", []),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    payload.update(claims)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def _auth(sub: str, **claims) -> dict:
    return {"Authorization": f"Bearer {_token(sub, **claims)}"}


def _scope(user_id):
    """Patch who is calling, at the helper the routes resolve the scope through."""
    return patch("agno.os.routers.metrics.metrics.get_scoped_user_id", return_value=user_id)


def _reads(db):
    return db.get_component_metrics.call_count + db.get_metrics_totals.call_count


def _databases():
    return {"updated_at": UPDATED_AT_ISO, "db_ids": {"db-1": UPDATED_AT_ISO}, "skipped_db_ids": {}}


# =============================================================================
# The shape of each route
# =============================================================================


class TestShapes:
    def test_sessions_compare_the_window_with_the_one_before(self, client, mock_db):
        """A two-day window ending today, compared with the two days before it, from one read."""
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(2)}").json()

        assert body == {
            "metrics": [
                {"date": _iso(_day(1)), "sessions_count": 1},
                {"date": _iso(_day(0)), "sessions_count": 3},
            ],
            "total_sessions": 4,
            "previous_total_sessions": 4,
            "change_percent": 0.0,
            "window_days": 2,
            **_databases(),
        }
        assert mock_db.get_component_metrics.call_args.kwargs == {
            "starting_date": _day(3),
            "ending_date": _day(0),
            "user_id": None,
            "fields": ["sessions_count"],
        }

    def test_tokens_compare_the_window_with_the_one_before(self, client):
        with _scope(None):
            body = client.get(f"/os/metrics/tokens?{_last(2)}").json()

        assert body == {
            "metrics": [
                {"date": _iso(_day(1)), "tokens_count": 100},
                {"date": _iso(_day(0)), "tokens_count": 300},
            ],
            "total_tokens": 400,
            "previous_total_tokens": 400,
            "change_percent": 0.0,
            "window_days": 2,
            **_databases(),
        }

    def test_runs_count_the_runs_no_other_run_started(self, client, mock_db):
        with _scope(None):
            body = client.get(f"/os/metrics/runs?{_last(2)}").json()

        assert body == {
            "metrics": [
                {"date": _iso(_day(1)), "runs_count": 2, "status_metrics": {"CANCELLED": 1, "COMPLETED": 1}},
                {"date": _iso(_day(0)), "runs_count": 4, "status_metrics": {"COMPLETED": 3, "ERROR": 1}},
            ],
            "total_runs": 6,
            "status_metrics": {"CANCELLED": 1, "COMPLETED": 4, "ERROR": 1},
            "success_rate": 66.7,
            "previous_total_runs": 2,
            "change_percent": 200.0,
            "window_days": 2,
            **_databases(),
        }
        assert mock_db.get_component_metrics.call_args.kwargs["fields"] == ["root_runs_count", "status_metrics"]

    def test_latency_gives_the_average_median_p95_and_max_of_each_day_and_the_window(self, client):
        with _scope(None):
            body = client.get(f"/os/metrics/latency?{_last(1)}").json()

        today = {
            "runs_count": 3,
            "avg_duration_ms": 2000,
            "median_duration_ms": 2250,
            "p95_duration_ms": 3850,
            "max_duration_ms": 4000,
            "avg_time_to_first_token_ms": 500,
            "median_time_to_first_token_ms": 800,
            "p95_time_to_first_token_ms": 800,
            "max_time_to_first_token_ms": 800,
            "avg_model_call_ms": 1000,
            "median_model_call_ms": 900,
            "p95_model_call_ms": 990,
            "max_model_call_ms": 2000,
        }
        assert body == {
            "metrics": [{"date": _iso(_day(0)), **today}],
            **today,
            "window_days": 1,
            **_databases(),
        }

    def test_models_share_the_window_runs_most_run_first(self, client, mock_db):
        with _scope(None):
            body = client.get(f"/os/metrics/models?{_last(2)}").json()

        assert body == {
            "models": [
                {"model_id": "gpt-5.5", "model_provider": "OpenAI", "runs_count": 4, "runs_share": 80.0},
                {"model_id": "claude-opus-5", "model_provider": "Anthropic", "runs_count": 1, "runs_share": 20.0},
            ],
            "total_model_runs": 5,
            "window_days": 2,
            **_databases(),
        }
        assert mock_db.get_metrics_totals.call_args.kwargs["fields"] == ["model_metrics"]


# =============================================================================
# ETag and kept answers
# =============================================================================


class TestETag:
    @pytest.mark.parametrize("route", KEPT_ROUTES)
    def test_answer_is_kept_and_a_caller_that_holds_its_etag_gets_a_304(self, client, mock_db, route):
        """The rows are read once while the versions stay the same; the 304 has no body and names the same ETag."""
        mock_db.get_metrics_versions = MagicMock(return_value=_versions())
        with _scope(None):
            first = client.get(f"/os/metrics/{route}?{_last(2)}")
            second = client.get(f"/os/metrics/{route}?{_last(2)}", headers={"If-None-Match": first.headers["etag"]})

        assert first.status_code == 200
        assert second.status_code == 304
        assert second.content == b""
        assert second.headers["etag"] == first.headers["etag"]
        assert _reads(mock_db) == 1


# =============================================================================
# The window and the databases
# =============================================================================


class TestWindow:
    def test_window_longer_than_the_setting_is_a_422(self, mock_db):
        client = _client(AgnoAPISettings(os_metrics_max_window_days=7), mock_db)
        with _scope(None):
            refused = client.get(f"/os/metrics/sessions?starting_date={_day(7).isoformat()}")
            answered = client.get(f"/os/metrics/sessions?starting_date={_day(6).isoformat()}")

        assert refused.status_code == 422
        assert answered.status_code == 200


class TestDatabases:
    def test_database_that_cannot_be_read_is_skipped(self, settings):
        """The other database still answers, and the response names the one left out and why."""
        broken = _db("db-2", _today_row())
        broken.get_component_metrics.side_effect = RuntimeError("boom")
        client = _client(settings, _db("db-1", _today_row()), broken)
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 3
        assert body["db_ids"] == {"db-1": UPDATED_AT_ISO}
        assert body["skipped_db_ids"] == {"db-2": "failed"}

    def test_one_client_under_two_ids_is_read_once(self, settings):
        """Two databases on one client, registered under two ids, count its rows once under the first id."""
        db_client = MagicMock()
        dbs = [MongoDb(db_client=db_client, id=db_id) for db_id in ["db-1", "db-2"]]
        for db in dbs:
            db.get_component_metrics = MagicMock(side_effect=_totals(_today_row()))  # type: ignore[method-assign]
            db.get_metrics_totals = MagicMock(side_effect=_window_totals(_today_row()))  # type: ignore[method-assign]
            db.get_metrics_versions = MagicMock(return_value=_versions())  # type: ignore[method-assign]
        client = _client(settings, *dbs)
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 3
        assert list(body["db_ids"]) == ["db-1"]

    def test_only_remote_database_answers_through_its_agentos(self, mock_db, settings):
        """A gateway whose one database is a RemoteDb forwards the read, with the caller's token and filters."""
        remote_client = _client(settings, mock_db)
        gateway_db = _remote_db("db-1", remote_client)
        gateway = _client(settings, gateway_db)
        with _scope(None):
            expected = remote_client.get(f"/os/metrics/sessions?{_last(2)}&user_id=alice").json()
            response = gateway.get(
                f"/os/metrics/sessions?{_last(2)}&user_id=alice&db_id=db-1",
                headers={"Authorization": "Bearer token-1"},
            )

        assert response.status_code == 200
        assert response.json() == expected
        assert response.headers["etag"]
        endpoint = gateway_db.client._aget.call_args.args[0]  # type: ignore[attr-defined]
        kwargs = gateway_db.client._aget.call_args.kwargs  # type: ignore[attr-defined]
        assert endpoint == "/os/metrics/sessions"
        assert kwargs["params"] == {
            "starting_date": _day(1).isoformat(),
            "user_id": "alice",
            "db_id": ["db-1"],
            "timeout_seconds": 30.0,
        }
        assert kwargs["headers"] == {"Authorization": "Bearer token-1"}

    def test_only_remote_database_reads_itself_alone_on_its_agentos(self, settings):
        """A gateway whose one database is a RemoteDb reads that database, not every database of the remote AgentOS."""
        remote_client = _client(settings, _db("db-1", _today_row()), _db("db-2", _today_row()))
        gateway = _client(settings, _remote_db("db-1", remote_client))
        with _scope(None):
            body = gateway.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 3
        assert list(body["db_ids"]) == ["db-1"]

    def test_remote_databases_of_one_agentos_answer_through_it_together(self, settings):
        """A gateway whose databases are RemoteDbs of one remote AgentOS forwards one read with all their ids."""
        remote_client = _client(settings, _db("db-1", _today_row()), _db("db-2", _today_row()))
        gateway_dbs = [_remote_db(db_id, remote_client) for db_id in ["db-1", "db-2"]]
        gateway = _client(settings, *gateway_dbs)
        with _scope(None):
            body = gateway.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 6
        assert list(body["db_ids"]) == ["db-1", "db-2"]
        assert gateway_dbs[0].client._aget.call_args.kwargs["params"]["db_id"] == ["db-1", "db-2"]  # type: ignore[attr-defined]
        gateway_dbs[1].client._aget.assert_not_called()  # type: ignore[attr-defined]


# =============================================================================
# GET /os/metrics/users
# =============================================================================


class TestUsers:
    def test_each_day_counts_everyone_added_up_to_its_end(self):
        """Three users added before the last two days, one yesterday and two today."""
        user_store = MagicMock()
        user_store.acreated_by_day = AsyncMock(
            side_effect=_created_by_day(_created_row(40, 1), _created_row(3, 2), _created_row(1, 1), _created_row(0, 2))
        )
        starting_date = _today() - timedelta(days=1)

        body = (
            _users_client({}, user_store=user_store)
            .get(f"/os/metrics/users?starting_date={starting_date.isoformat()}")
            .json()
        )

        assert body.pop("updated_at")
        assert body == {
            "metrics": [
                {"date": _iso(_today() - timedelta(days=1)), "users_count": 4},
                {"date": _iso(_today()), "users_count": 6},
            ],
            "total_users": 6,
            "previous_total_users": 3,
            "change_percent": 100.0,
            "window_days": 2,
        }

    def test_remote_database_answers_from_its_agentos_directory(self):
        """A gateway with no directory whose database is a RemoteDb forwards the read to the remote AgentOS."""
        user_store = MagicMock()
        user_store.acreated_by_day = AsyncMock(side_effect=_created_by_day(_created_row(3, 2), _created_row(0, 1)))
        remote_client = _users_client({}, user_store=user_store)
        gateway = _users_client({"db-1": [_remote_db("db-1", remote_client)]})

        response = gateway.get("/os/metrics/users")

        assert response.status_code == 200
        assert response.json()["total_users"] == 3

    def test_remote_database_is_not_read_for_a_caller_who_is_not_an_admin(self):
        """A gateway refuses a caller who is not its admin before forwarding the read to the remote AgentOS."""
        agentos_client = AgentOSClient(base_url="http://remote-os")
        agentos_client._aget = AsyncMock()  # type: ignore[method-assign]
        require_admin = AsyncMock(side_effect=HTTPException(status_code=403, detail="Admin privileges required"))
        gateway = _users_client({"db-1": [RemoteDb(id="db-1", client=agentos_client)]}, require_admin=require_admin)

        response = gateway.get("/os/metrics/users")

        assert response.status_code == 403
        agentos_client._aget.assert_not_called()

    def test_remote_refusal_is_passed_through_without_the_remote_url(self):
        """A remote AgentOS that refuses the read is answered with its status, not a 500 naming its URL."""
        agentos_client = AgentOSClient(base_url="http://remote-os")
        remote_response = httpx.Response(
            403,
            json={"detail": "Admin privileges required"},
            request=httpx.Request("GET", "http://remote-os/os/metrics/users"),
        )
        agentos_client._aget = AsyncMock(side_effect=lambda *args, **kwargs: remote_response.raise_for_status())  # type: ignore[method-assign]
        gateway = _users_client({"db-1": [RemoteDb(id="db-1", client=agentos_client)]})

        response = gateway.get("/os/metrics/users")

        assert response.status_code == 403
        assert response.json()["detail"] == "Admin privileges required"
        assert "http://" not in response.text

    def test_member_without_the_admin_scope_is_refused_and_an_admin_answered(self, tmp_path):
        """Served through AgentOS with real tokens, so the admin gate is the one the /users API uses."""
        db = SqliteDb(db_file=str(tmp_path / "users.db"))
        authorization = Authorization(verification_keys=[SECRET], algorithm="HS256", audience=OS_ID)
        agent_os = AgentOS(
            agents=[Agent(id="assistant", db=db)], db=db, user_directory=True, authorization=authorization
        )
        client = TestClient(agent_os.get_app())

        member = client.get("/os/metrics/users", headers=_auth("alice", scopes=["metrics:read"]))
        admin = client.get("/os/metrics/users", headers=_auth("admin", scopes=["agent_os:admin"]))

        assert member.status_code == 403
        assert admin.status_code == 200
