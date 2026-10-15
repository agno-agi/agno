"""Tests for GET /os/metrics/users on the metrics router."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, Authorization, create_dev_token
from agno.os.routers.metrics.metrics import get_metrics_router
from agno.os.settings import AgnoAPISettings

# =============================================================================
# Fixtures
# =============================================================================


def _today():
    """Today in UTC, the day a default window ends on."""
    return datetime.now(timezone.utc).date()


def _last(days):
    """Query string for the window of the last ``days`` days, ending today."""
    start = _today() - timedelta(days=days - 1)
    return f"starting_date={start.isoformat()}"


def _day(days_ago, count):
    """A row of the directory's users-created-per-day read, keyed by the day's start in epoch seconds."""
    day = _today() - timedelta(days=days_ago)
    return {"date": int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()), "count": count}


def _created_by_day(*rows):
    """Answer each directory read with the rows created before the bound it asks for."""

    async def read(starting_at=None, ending_before=None):
        return [row for row in rows if ending_before is None or row["date"] < ending_before]

    return read


@pytest.fixture
def settings():
    return AgnoAPISettings()


@pytest.fixture
def user_store():
    """Three users added before the last two days, one yesterday and two today."""
    store = MagicMock()
    store.acreated_by_day = AsyncMock(side_effect=_created_by_day(_day(40, 1), _day(3, 2), _day(1, 1), _day(0, 2)))
    return store


@pytest.fixture
def require_user_admin():
    return AsyncMock(return_value="")


@pytest.fixture
def client(user_store, require_user_admin, settings):
    app = FastAPI()
    app.state.user_store = user_store
    with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
        with patch("agno.os.routers.metrics.metrics._make_require_admin", return_value=require_user_admin):
            app.include_router(get_metrics_router(dbs={}, settings=settings))
    return TestClient(app)


# =============================================================================
# GET /os/metrics/users
# =============================================================================


class TestUserCounts:
    def test_each_day_counts_everyone_added_up_to_its_end(self, client):
        body = client.get(f"/os/metrics/users?{_last(2)}").json()

        assert body["metrics"] == [
            {"date": f"{(_today() - timedelta(days=1)).isoformat()}T00:00:00Z", "users_count": 4},
            {"date": f"{_today().isoformat()}T00:00:00Z", "users_count": 6},
        ]
        assert body["total_users"] == 6

    def test_change_is_against_the_directory_at_the_end_of_the_window_before(self, client):
        """A two-day window ending today is compared with the directory as it stood two days ago."""
        body = client.get(f"/os/metrics/users?{_last(2)}").json()

        assert body["previous_total_users"] == 3
        assert body["change_percent"] == 100.0

    def test_past_window_reports_only_counts_of_its_own_days(self, client):
        """Nothing in the response describes the directory as it is now, so a past window cannot contradict itself."""
        two_days_ago = _today() - timedelta(days=2)
        body = client.get(
            f"/os/metrics/users?starting_date={two_days_ago.isoformat()}&ending_date={two_days_ago.isoformat()}"
        ).json()

        assert body["total_users"] == 3

    def test_no_users_before_means_no_rate(self, client, user_store):
        """A window with nobody before it cannot show an infinite rise."""
        user_store.acreated_by_day.side_effect = _created_by_day(_day(0, 3))
        body = client.get(f"/os/metrics/users?{_last(1)}").json()

        assert body["total_users"] == 3
        assert body["previous_total_users"] == 0
        assert body["change_percent"] is None

    def test_every_day_of_the_window_is_returned(self, client):
        """A day nobody was added on repeats the count of the day before it."""
        body = client.get(f"/os/metrics/users?{_last(5)}").json()

        assert [entry["users_count"] for entry in body["metrics"]] == [1, 3, 3, 4, 6]

    def test_users_added_after_the_window_are_not_counted(self, client):
        yesterday = _today() - timedelta(days=1)
        body = client.get(
            f"/os/metrics/users?starting_date={yesterday.isoformat()}&ending_date={yesterday.isoformat()}"
        ).json()

        assert body["total_users"] == 4
        assert body["previous_total_users"] == 3

    def test_both_windows_come_from_one_read_of_the_directory(self, client, user_store):
        client.get(f"/os/metrics/users?{_last(2)}")

        user_store.acreated_by_day.assert_awaited_once()
        tomorrow = _today() + timedelta(days=1)
        assert user_store.acreated_by_day.await_args.kwargs == {
            "ending_before": int(datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        }


# =============================================================================
# Access to GET /os/metrics/users
# =============================================================================


class TestAccess:
    def test_directory_admin_gate_decides(self, client, user_store, require_user_admin):
        require_user_admin.side_effect = HTTPException(status_code=403, detail="Admin privileges required")
        resp = client.get("/os/metrics/users")

        assert resp.status_code == 403
        user_store.acreated_by_day.assert_not_awaited()

    def test_os_without_a_user_directory_has_no_user_metrics(self):
        app = FastAPI()
        with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
            app.include_router(get_metrics_router(dbs={}, settings=AgnoAPISettings()))
        resp = TestClient(app).get("/os/metrics/users")

        assert resp.status_code == 503

    def test_window_may_cover_more_than_a_year(self, client):
        resp = client.get(f"/os/metrics/users?{_last(400)}")

        assert resp.status_code == 200
        assert len(resp.json()["metrics"]) == 400


class TestAccessOnAnAgentOS:
    """Served through AgentOS with real tokens, so the admin gate is the one the /users API uses."""

    SECRET = "users-metrics-secret-at-least-256-bits-long"

    def _client(self, tmp_path, **kwargs):
        db = SqliteDb(db_file=str(tmp_path / "users.db"))
        agent_os = AgentOS(agents=[Agent(id="assistant", db=db)], db=db, user_directory=True, **kwargs)
        return TestClient(agent_os.get_app())

    def _token(self, sub, scopes):
        return {
            "Authorization": f"Bearer {create_dev_token(sub, secret=self.SECRET, audience='users-os', scopes=scopes)}"
        }

    def test_member_without_the_admin_scope_is_refused_even_without_user_isolation(self, tmp_path):
        authorization = Authorization(verification_keys=[self.SECRET], algorithm="HS256", audience="users-os")
        client = self._client(tmp_path, authorization=authorization)

        member = client.get("/os/metrics/users", headers=self._token("alice", ["metrics:read"]))
        admin = client.get("/os/metrics/users", headers=self._token("admin", ["agent_os:admin"]))

        assert member.status_code == 403
        assert client.get("/users/metrics", headers=self._token("alice", ["metrics:read"])).status_code == 403
        assert admin.status_code == 200

    def test_caller_without_a_token_is_refused(self, tmp_path):
        authorization = Authorization(verification_keys=[self.SECRET], algorithm="HS256", audience="users-os")
        client = self._client(tmp_path, authorization=authorization)

        assert client.get("/os/metrics/users").status_code == 401

    def test_os_without_auth_answers_like_the_users_api(self, tmp_path):
        """With no auth every route is open, the /users API included."""
        client = self._client(tmp_path)

        assert client.get("/os/metrics/users").status_code == 200
        assert client.get("/users/metrics").status_code == 200

    def test_empty_directory_behind_a_security_key_is_unavailable(self, tmp_path, monkeypatch):
        """A security key names no caller, so nobody is ever added and a zero would never change."""
        monkeypatch.setenv("OS_SECURITY_KEY", "users-metrics-key")
        client = self._client(tmp_path)

        resp = client.get("/os/metrics/users", headers={"Authorization": "Bearer users-metrics-key"})

        assert resp.status_code == 503

    def test_directory_with_users_behind_a_security_key_answers_every_window(self, tmp_path, monkeypatch):
        """Once an admin adds someone, a window ending before them reads zero rather than unavailable."""
        monkeypatch.setenv("OS_SECURITY_KEY", "users-metrics-key")
        client = self._client(tmp_path)
        key = {"Authorization": "Bearer users-metrics-key"}
        client.post("/users", json={"id": "dana", "email": "dana@example.com"}, headers=key)
        last_week = _today() - timedelta(days=7)

        resp = client.get(
            f"/os/metrics/users?starting_date={last_week.isoformat()}&ending_date={last_week.isoformat()}", headers=key
        )

        assert resp.status_code == 200
        assert resp.json()["total_users"] == 0
