"""Tests for GET /os/metrics/users on the metrics router."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
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


def _iso(day):
    return f"{day.isoformat()}T00:00:00Z"


def _created_row(days_ago, count):
    """A row of the directory's users-created-per-day read, keyed by the day's start in epoch seconds."""
    day = _today() - timedelta(days=days_ago)
    return {"date": int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()), "count": count}


def _created_by_day(*rows):
    """Answer each directory read with the rows created before the bound it asks for."""

    async def read(starting_at=None, ending_before=None):
        return [row for row in rows if ending_before is None or row["date"] < ending_before]

    return read


# =============================================================================
# GET /os/metrics/users
# =============================================================================


class TestUserCounts:
    def test_each_day_counts_everyone_added_up_to_its_end(self):
        """Three users added before the last two days, one yesterday and two today."""
        user_store = MagicMock()
        user_store.acreated_by_day = AsyncMock(
            side_effect=_created_by_day(_created_row(40, 1), _created_row(3, 2), _created_row(1, 1), _created_row(0, 2))
        )
        app = FastAPI()
        app.state.user_store = user_store
        with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
            with patch("agno.os.routers.metrics.metrics._make_require_admin", return_value=AsyncMock(return_value="")):
                app.include_router(get_metrics_router(dbs={}, settings=AgnoAPISettings()))
        starting_date = _today() - timedelta(days=1)

        body = TestClient(app).get(f"/os/metrics/users?starting_date={starting_date.isoformat()}").json()

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


# =============================================================================
# Access to GET /os/metrics/users
# =============================================================================


class TestAccessOnAnAgentOS:
    """Served through AgentOS with real tokens, so the admin gate is the one the /users API uses."""

    SECRET = "users-metrics-secret-at-least-256-bits-long"

    def _token(self, sub, scopes):
        return {
            "Authorization": f"Bearer {create_dev_token(sub, secret=self.SECRET, audience='users-os', scopes=scopes)}"
        }

    def test_member_without_the_admin_scope_is_refused_and_an_admin_answered(self, tmp_path):
        db = SqliteDb(db_file=str(tmp_path / "users.db"))
        authorization = Authorization(verification_keys=[self.SECRET], algorithm="HS256", audience="users-os")
        agent_os = AgentOS(
            agents=[Agent(id="assistant", db=db)], db=db, user_directory=True, authorization=authorization
        )
        client = TestClient(agent_os.get_app())

        member = client.get("/os/metrics/users", headers=self._token("alice", ["metrics:read"]))
        admin = client.get("/os/metrics/users", headers=self._token("admin", ["agent_os:admin"]))

        assert member.status_code == 403
        assert admin.status_code == 200
