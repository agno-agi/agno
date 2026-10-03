"""REST mints component ids the way StudioTools does.

An id is a URL path segment and it is embedded in schedule run endpoints.
The loose generator keeps whatever a display name contains, so a name like
"Reports/Q3 Agent" produced an id with a path separator in it. Such a row is
unreachable through every /components/{id} route -- and worse, a "/" in the
id defeats RUN_ENDPOINT_RE, so the schedule guards that inspect a run
endpoint stop recognising it and fail open.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings
from agno.utils.string import validate_component_id


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="mint-db", db_file=str(tmp_path / "mint.db"))


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app)


def _create(client, **body):
    return client.post("/components", json={"component_type": "agent", "config": {}, **body})


class TestTheMintIsStrict:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Reports/Q3 Agent", "reports-q3-agent"),
            ("Q&A Helper", "q-a-helper"),
            ("weird?name#here", "weird-name-here"),
        ],
    )
    def test_a_display_name_never_yields_a_path_segment(self, client, name, expected):
        r = _create(client, name=name)
        assert r.status_code == 201, (r.status_code, r.text)
        assert r.json()["component_id"] == expected

    def test_the_minted_id_round_trips_through_the_path_routes(self, client):
        component_id = _create(client, name="Reports/Q3 Agent").json()["component_id"]
        assert client.get(f"/components/{component_id}").status_code == 200


class TestAnExplicitIdIsValidated:
    @pytest.mark.parametrize("component_id", ["reports/q3", "a b", "back\\slash", "q?uery", "frag#ment", ".", ".."])
    def test_an_unusable_id_is_refused(self, client, component_id):
        r = _create(client, name="X", component_id=component_id)
        assert r.status_code == 400, (r.status_code, r.text)
        assert "component_id" in r.json()["detail"]

    def test_a_usable_id_is_accepted(self, client):
        r = _create(client, name="X", component_id="reports-q3")
        assert r.status_code == 201, (r.status_code, r.text)
        assert r.json()["component_id"] == "reports-q3"

    def test_unicode_letters_are_still_allowed(self, client):
        r = _create(client, name="X", component_id="café-agent")
        assert r.status_code == 201, (r.status_code, r.text)


class TestTheSharedRuleRefusesPathSegments:
    def test_dot_and_dotdot_are_rejected(self):
        assert validate_component_id(".") is not None
        assert validate_component_id("..") is not None

    def test_a_name_containing_dots_is_fine(self):
        assert validate_component_id("v1.2.agent") is None
