"""A rollback re-projects the version it rolls to, including its silences.

Publishing re-projects name/description/metadata onto the catalog row inside
the pointer transaction. A pointer moved any other way -- a rollback through
PATCH /components/{id} -- has to do the same, or listings keep serving the
identity of a version that is no longer live.

The subtlety is the cleared field: the adapters read None as "leave this
column alone", so projecting only the non-None fields leaves the PREVIOUS
version's description and metadata on the row.
"""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.components import components as components_module
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
    """v1 clears both fields explicitly; v2 carries a description and metadata."""
    db.create_component_with_config(
        component_id="roller",
        component_type=ComponentType.AGENT,
        name="roller",
        config={"name": "roller", "description": ""},
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

    def test_the_metadata_the_new_live_version_lacks_is_left_alone(self, client, db, two_versions):
        """Metadata follows the adapter's publish rule: projected only when the
        rolled-to version actually carries some."""
        client.patch(f"/components/{two_versions}", json={"current_version": 1})
        assert db.get_component(two_versions)["metadata"] == {"tier": "gold"}

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


class TestRowOnlyFieldsSurviveAPointerMove:
    """description and metadata are also first-class columns, set through
    POST/PATCH /components and never written into any config. A projection
    that read "absent from the config" as "cleared" destroyed them on the
    next pointer move, with no version to restore them from.
    """

    @pytest.fixture
    def row_only(self, client, db):
        r = client.post(
            "/components",
            json={
                "name": "Invoices",
                "component_type": "agent",
                "description": "Handles invoices",
                "metadata": {"team": "finance"},
                "config": {"name": "Invoices"},
                "stage": "published",
            },
        )
        assert r.status_code == 201, r.text
        component_id = r.json()["component_id"]
        db.upsert_config(component_id, config={"name": "Invoices"}, stage="published")
        return component_id

    def test_the_description_survives_a_pointer_move(self, client, db, row_only):
        assert client.patch(f"/components/{row_only}", json={"current_version": 1}).status_code == 200
        assert db.get_component(row_only)["description"] == "Handles invoices"

    def test_the_metadata_survives_a_pointer_move(self, client, db, row_only):
        client.patch(f"/components/{row_only}", json={"current_version": 1})
        assert db.get_component(row_only)["metadata"] == {"team": "finance"}

    def test_the_set_current_route_agrees(self, client, db, row_only):
        assert client.post(f"/components/{row_only}/configs/1/set-current").status_code == 200
        row = db.get_component(row_only)
        assert row["description"] == "Handles invoices"
        assert row["metadata"] == {"team": "finance"}

    def test_stamp_only_metadata_does_not_claim_the_column(self, client, db, row_only):
        # A scoped save stamps provenance into every config's metadata; the
        # stamp alone is not authored metadata and must not replace the row's.
        db.upsert_config(
            row_only,
            config={"name": "Invoices", "metadata": {"studio": {"last_actor": "builder-1"}}},
            stage="published",
        )
        assert client.patch(f"/components/{row_only}", json={"current_version": 1}).status_code == 200
        assert client.patch(f"/components/{row_only}", json={"current_version": 3}).status_code == 200
        assert db.get_component(row_only)["metadata"] == {"team": "finance"}

    def test_the_authored_marker_makes_stamp_only_metadata_win(self, client, db, row_only):
        db.upsert_config(
            row_only,
            config={
                "name": "Invoices",
                "metadata": {"studio": {"last_actor": "builder-1"}},
                "metadata_authored": True,
            },
            stage="published",
        )
        assert client.patch(f"/components/{row_only}", json={"current_version": 1}).status_code == 200
        assert client.patch(f"/components/{row_only}", json={"current_version": 3}).status_code == 200
        assert db.get_component(row_only)["metadata"] == {"studio": {"last_actor": "builder-1"}}


class TestANonMappingMetadataStillPublishes:
    """The projection says which row fields a version owns; it does not get to
    decide which configs are writable. Asking a scalar for its keys raised, and
    the route's catch-all turned a publish the adapters used to accept into a
    500. A value that cannot be a row's metadata is not owned either: it stays
    in the config and the column keeps what it had, because a scalar on the
    column makes the component - and every listing that includes it -
    unreadable.
    """

    @pytest.fixture
    def component_id(self, client):
        r = client.post(
            "/components",
            json={
                "component_id": "a1",
                "component_type": "agent",
                "name": "A1",
                "metadata": {"team": "ops"},
                "config": {"name": "A1"},
            },
        )
        assert r.status_code == 201, r.text
        return "a1"

    @pytest.mark.parametrize("metadata", [5, "hello", ["a", "b"], ["studio"], True])
    def test_the_publish_is_accepted_and_the_row_column_is_left_alone(self, client, db, component_id, metadata):
        r = client.post(
            f"/components/{component_id}/configs",
            json={"config": {"name": "A1", "metadata": metadata}, "stage": "published"},
        )
        assert r.status_code == 201, (r.status_code, r.text)
        assert r.json()["config"]["metadata"] == metadata
        assert db.get_component(component_id)["metadata"] == {"team": "ops"}

    def test_the_catalog_stays_readable(self, client, component_id):
        """The point of skipping the column: one config the projection cannot
        store must not take out reads of the component, nor of the whole
        listing that carries unrelated components alongside it."""
        other = client.post(
            "/components",
            json={"component_id": "b2", "component_type": "agent", "name": "B2", "config": {"name": "B2"}},
        )
        assert other.status_code == 201, other.text

        published = client.post(
            f"/components/{component_id}/configs",
            json={"config": {"name": "A1", "metadata": 5}, "stage": "published"},
        )
        assert published.status_code == 201, (published.status_code, published.text)

        one = client.get(f"/components/{component_id}")
        assert one.status_code == 200, (one.status_code, one.text)

        listing = client.get("/components")
        assert listing.status_code == 200, (listing.status_code, listing.text)
        listed = listing.json()
        rows = listed["data"] if isinstance(listed, dict) else listed
        assert {row["component_id"] for row in rows} >= {component_id, "b2"}


class TestAProjectionFailureDoesNotFailACommittedPointerMove:
    """The pointer move commits before the row is re-projected. A projection
    that blows up leaves the row stale, which is recoverable; answering 500 for
    a rollback that actually happened is not -- the caller retries or reports a
    failure that never was.
    """

    @pytest.fixture
    def exploding_projection(self, monkeypatch):
        def boom(config):
            raise TypeError("projection exploded")

        monkeypatch.setattr(components_module, "project_config_identity", boom)

    def test_the_set_current_route_still_succeeds(self, client, db, two_versions, exploding_projection, caplog):
        with caplog.at_level(logging.WARNING, logger="agno"):
            r = client.post(f"/components/{two_versions}/configs/1/set-current")
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json()["current_version"] == 1
        assert db.get_component(two_versions)["current_version"] == 1
        assert any("could not re-project" in record.message for record in caplog.records)

    def test_the_patch_route_still_succeeds(self, client, db, two_versions, exploding_projection, caplog):
        with caplog.at_level(logging.WARNING, logger="agno"):
            r = client.patch(f"/components/{two_versions}", json={"current_version": 1})
        assert r.status_code == 200, (r.status_code, r.text)
        assert db.get_component(two_versions)["current_version"] == 1
        assert any("could not re-project" in record.message for record in caplog.records)

    def test_a_field_the_request_sets_itself_still_lands(self, client, db, two_versions, exploding_projection):
        r = client.patch(f"/components/{two_versions}", json={"current_version": 1, "description": "explicit"})
        assert r.status_code == 200, (r.status_code, r.text)
        assert db.get_component(two_versions)["description"] == "explicit"


class TestAFailedProjectionWriteDoesNotFailACommittedPointerMove:
    """A PATCH body that carries nothing but current_version leaves the trailing
    upsert holding the projection alone, so that write IS the re-projection --
    and it must answer like the sibling set-current route does, not 500 for a
    pointer move that has already committed. A body that also sets fields of
    its own is a real update, and its failure is still reported."""

    @pytest.fixture
    def exploding_projection_write(self, db, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("row write exploded")

        monkeypatch.setattr(db, "upsert_component", boom)

    def test_a_bare_pointer_move_still_succeeds(self, client, db, two_versions, exploding_projection_write, caplog):
        with caplog.at_level(logging.WARNING, logger="agno"):
            r = client.patch(f"/components/{two_versions}", json={"current_version": 1})
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json()["current_version"] == 1
        assert db.get_component(two_versions)["current_version"] == 1
        assert any("could not re-project" in record.message for record in caplog.records)

    def test_a_body_that_sets_a_field_itself_still_reports_the_failure(
        self, client, db, two_versions, exploding_projection_write
    ):
        r = client.patch(f"/components/{two_versions}", json={"current_version": 1, "description": "explicit"})
        assert r.status_code == 500, (r.status_code, r.text)

    def test_a_plain_field_update_still_reports_the_failure(self, client, db, two_versions, exploding_projection_write):
        r = client.patch(f"/components/{two_versions}", json={"description": "explicit"})
        assert r.status_code == 500, (r.status_code, r.text)

    def test_a_body_that_changes_nothing_still_reports_the_failure(
        self, client, two_versions, exploding_projection_write
    ):
        """A body with neither fields of its own nor a pointer move: nothing
        committed ahead of this write for it to be the re-projection of, so
        the failure is this request's own and the caller hears it."""
        r = client.patch(f"/components/{two_versions}", json={})
        assert r.status_code == 500, (r.status_code, r.text)

    def test_the_pointer_move_itself_is_still_reported(self, client, db, two_versions, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("pointer write exploded")

        monkeypatch.setattr(db, "set_current_version", boom)
        assert client.patch(f"/components/{two_versions}", json={"current_version": 1}).status_code == 500
