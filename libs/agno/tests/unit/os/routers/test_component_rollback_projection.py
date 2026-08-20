"""A rollback re-projects the version it rolls to, including its silences.

Publishing re-projects name/description/metadata onto the catalog row inside
the pointer transaction. A pointer moved any other way -- a rollback through
PATCH /components/{id} -- has to do the same, or listings keep serving the
identity of a version that is no longer live.

The subtlety is the cleared field: the adapters read None as "leave this
column alone", so projecting only the non-None fields leaves the PREVIOUS
version's description and metadata on the row.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="rollback-db", db_file=str(tmp_path / "rollback.db"))


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app)


@pytest.fixture
def two_versions(db):
    """v1 is bare; v2 carries a description and metadata."""
    db.create_component_with_config(
        component_id="roller",
        component_type=ComponentType.AGENT,
        name="roller",
        config={"name": "roller"},
        stage="published",
    )
    db.upsert_config(
        "roller",
        config={"name": "roller v2", "description": "the second one", "metadata": {"tier": "gold"}},
        stage="published",
    )
    db.set_current_version("roller", version=2)
    return "roller"


class TestRollingBackToABarerVersion:
    def test_the_description_the_new_live_version_lacks_is_cleared(self, client, db, two_versions):
        r = client.patch(f"/components/{two_versions}", json={"current_version": 1})
        assert r.status_code == 200, (r.status_code, r.text)
        assert not db.get_component(two_versions).get("description")

    def test_the_metadata_the_new_live_version_lacks_is_cleared(self, client, db, two_versions):
        client.patch(f"/components/{two_versions}", json={"current_version": 1})
        assert not db.get_component(two_versions).get("metadata")

    def test_the_name_falls_back_rather_than_emptying(self, client, db, two_versions):
        client.patch(f"/components/{two_versions}", json={"current_version": 1})
        assert db.get_component(two_versions)["name"] == "roller"

    def test_rolling_forward_still_projects_the_richer_version(self, client, db, two_versions):
        client.patch(f"/components/{two_versions}", json={"current_version": 1})
        client.patch(f"/components/{two_versions}", json={"current_version": 2})
        row = db.get_component(two_versions)
        assert row["description"] == "the second one"
        assert row["metadata"] == {"tier": "gold"}

    def test_a_field_set_by_the_same_request_still_wins(self, client, db, two_versions):
        r = client.patch(f"/components/{two_versions}", json={"current_version": 1, "description": "explicit"})
        assert r.status_code == 200, (r.status_code, r.text)
        assert db.get_component(two_versions)["description"] == "explicit"
