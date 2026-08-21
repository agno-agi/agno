"""The catalog row always describes the version the live pointer names.

Two rules this pins:

* Re-publishing a version that is already published writes nothing. It is a
  no-op, so it must not re-project that version's name/description/metadata
  onto the component row -- doing so makes the row describe a version that is
  not live, and the display-name tier resolves components by that column.
* The compare-and-set guard is answered before that no-op returns, so a stale
  guard is a version_conflict rather than a success envelope.

And the projection itself: a field the published version does not carry was
cleared, so the row must lose it too. The adapters read ``None`` as "leave the
column alone", which is why an emptied description kept being served by
list_components long after it was gone.
"""

import asyncio
import json
from typing import Any, Dict

import pytest

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.studio import StudioTools


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="studio-projection-db", db_file=str(tmp_path / "projection.db"))


@pytest.fixture
def registry(db):
    return Registry(name="Projection Registry", models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])


@pytest.fixture
def studio(registry, db):
    return StudioTools(registry=registry, db=db)


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


def _data(s: str) -> Dict[str, Any]:
    out = json.loads(s)
    assert out.get("ok") is True, out
    return out["data"]


def _error(s: str) -> Dict[str, Any]:
    out = json.loads(s)
    assert out.get("ok") is False, out
    return out["error"]


def _row_identity(db, component_id: str) -> Dict[str, Any]:
    row = db.get_component(component_id) or {}
    return {k: row.get(k) for k in ("name", "description", "metadata", "current_version")}


def _rollback_fixture(studio, db) -> str:
    """v1 'Alpha Bot' published and live, v2 'Beta Bot' published but rolled back."""
    created = _data(
        studio.create_agent(
            name="Alpha Bot",
            instructions="be alpha",
            description="alpha desc",
            metadata={"tier": "one"},
            publish=True,
        )
    )
    component_id = created["id"]
    _data(
        studio.edit_agent(
            agent_id=component_id,
            name="Beta Bot",
            description="beta desc",
            metadata={"tier": "two"},
            publish=True,
        )
    )
    _data(studio.set_current_version(component_id, 1))
    assert _row_identity(db, component_id) == {
        "name": "Alpha Bot",
        "description": "alpha desc",
        "metadata": {"tier": "one"},
        "current_version": 1,
    }
    return component_id


# ----------------------------------------------------------------------
# The already-published branch writes nothing
# ----------------------------------------------------------------------


class TestRepublishIsReallyANoOp:
    def test_republish_leaves_the_catalog_row_alone(self, studio, db):
        component_id = _rollback_fixture(studio, db)
        before = _row_identity(db, component_id)

        out = _loads(studio.publish_component(component_id, version=2))
        assert out["status"] == "already_published"

        assert _row_identity(db, component_id) == before

    def test_republish_does_not_break_live_display_name_resolution(self, studio, db):
        component_id = _rollback_fixture(studio, db)
        studio.publish_component(component_id, version=2)

        # v1 is live and its config name is 'Alpha Bot'; the row must still say so.
        assert _data(studio.get_component("Alpha Bot"))["id"] == component_id
        assert _error(studio.get_component("Beta Bot"))["code"] == "component_not_found"

    def test_async_republish_leaves_the_catalog_row_alone(self, studio, db):
        component_id = _rollback_fixture(studio, db)
        before = _row_identity(db, component_id)

        out = _loads(asyncio.run(studio.apublish_component(component_id, version=2)))
        assert out["status"] == "already_published"

        assert _row_identity(db, component_id) == before


# ----------------------------------------------------------------------
# The CAS guard is answered before that no-op returns
# ----------------------------------------------------------------------


class TestPublishCasOnAnAlreadyPublishedVersion:
    def test_stale_guard_is_a_version_conflict(self, studio, db):
        component_id = _rollback_fixture(studio, db)

        error = _error(studio.publish_component(component_id, version=2, expected_current_version=999))
        assert error["code"] == "version_conflict"
        assert error["retryable"] is True
        assert error["details"]["current_version"] == 1

    def test_async_stale_guard_is_a_version_conflict(self, studio, db):
        component_id = _rollback_fixture(studio, db)

        error = _error(asyncio.run(studio.apublish_component(component_id, version=2, expected_current_version=999)))
        assert error["code"] == "version_conflict"

    def test_matching_guard_still_reports_already_published(self, studio, db):
        component_id = _rollback_fixture(studio, db)

        out = _loads(studio.publish_component(component_id, version=2, expected_current_version=1))
        assert out["status"] == "already_published"
        assert out["data"]["version"] == 2

    def test_an_unknown_version_is_still_reported_before_the_guard(self, studio, db):
        component_id = _rollback_fixture(studio, db)

        # A bad argument outranks optimistic concurrency: retrying cannot help.
        error = _error(studio.publish_component(component_id, version=99, expected_current_version=999))
        assert error["code"] == "version_not_found"


# ----------------------------------------------------------------------
# A cleared field is cleared on the row too
# ----------------------------------------------------------------------


class TestClearedFieldsReachTheCatalogRow:
    @staticmethod
    def _create(studio, component_type: str, name: str) -> str:
        if component_type == "agent":
            out = studio.create_agent(
                name=name, instructions="i", description="ORIGINAL", metadata={"keep": "me"}, publish=True
            )
        elif component_type == "team":
            studio.create_agent(name=f"{name}-member", instructions="i", publish=True)
            out = studio.create_team(
                name=name,
                instructions="i",
                member_ids=[f"{name}-member"],
                description="ORIGINAL",
                metadata={"keep": "me"},
                publish=True,
            )
        else:
            studio.create_agent(name=f"{name}-step", instructions="i", publish=True)
            out = studio.create_workflow(
                name=name,
                steps=[{"type": "step", "name": "s1", "agent_id": f"{name}-step"}],
                description="ORIGINAL",
                metadata={"keep": "me"},
                publish=True,
            )
        return _data(out)["id"]

    @staticmethod
    def _edit(studio, component_type: str, component_id: str, **kwargs) -> Dict[str, Any]:
        editor = {
            "agent": studio.edit_agent,
            "team": studio.edit_team,
            "workflow": studio.edit_workflow,
        }[component_type]
        return _data(editor(component_id, **kwargs))

    @pytest.mark.parametrize("component_type", ["agent", "team", "workflow"])
    def test_publishing_a_cleared_description_clears_the_row(self, studio, db, component_type):
        component_id = self._create(studio, component_type, f"clear-{component_type}")
        assert db.get_component(component_id)["description"] == "ORIGINAL"

        self._edit(studio, component_type, component_id, description="")
        _data(studio.publish_component(component_id))

        assert not db.get_component(component_id)["description"]
        rows, _ = db.list_components()
        listed = next(r for r in rows if r["component_id"] == component_id)
        assert not listed["description"]

    def test_publishing_a_cleared_description_inline_clears_the_row(self, studio, db):
        # publish=True on the edit takes the direct-publish path, not publish_component.
        component_id = self._create(studio, "agent", "clear-inline")
        self._edit(studio, "agent", component_id, description="", publish=True)

        assert not db.get_component(component_id)["description"]

    def test_publishing_cleared_metadata_clears_the_row(self, studio, db):
        component_id = self._create(studio, "agent", "clear-meta")
        assert db.get_component(component_id)["metadata"] == {"keep": "me"}

        self._edit(studio, "agent", component_id, metadata={})
        _data(studio.publish_component(component_id))

        assert not db.get_component(component_id)["metadata"]

    def test_rolling_forward_onto_a_cleared_version_clears_the_row(self, studio, db):
        component_id = self._create(studio, "agent", "clear-pointer")
        self._edit(studio, "agent", component_id, description="", publish=True)
        # Roll back to the version that still has the text, then forward again.
        _data(studio.set_current_version(component_id, 1))
        assert db.get_component(component_id)["description"] == "ORIGINAL"

        _data(studio.set_current_version(component_id, 2))
        assert not db.get_component(component_id)["description"]

    def test_async_publish_of_a_cleared_description_clears_the_row(self, studio, db):
        component_id = self._create(studio, "agent", "clear-async")
        self._edit(studio, "agent", component_id, description="")

        _data(asyncio.run(studio.apublish_component(component_id)))

        assert not db.get_component(component_id)["description"]
