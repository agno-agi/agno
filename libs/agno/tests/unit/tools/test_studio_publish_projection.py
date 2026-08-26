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
import logging
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


# ----------------------------------------------------------------------
# Row-only fields survive the toolkit's pointer moves
# ----------------------------------------------------------------------


def _operator_patch(db, component_id: str) -> None:
    """The write PATCH /components performs: row columns only, no config."""
    from agno.db.base import ComponentType

    row = db.get_component(component_id)
    merged = dict(row.get("metadata") or {})
    merged["team"] = "ops"
    db.upsert_component(
        component_id=component_id,
        component_type=ComponentType(row["component_type"]),
        name=row["name"],
        description="operator note",
        metadata=merged,
    )


def _create_bare(studio, component_type: str, name: str, ctx=None) -> str:
    """A published component whose configs never carry description/metadata.

    With ``ctx`` the component is owned by that caller, which is what a scoped
    actor needs before it may edit the component at all.
    """
    scope = {"_agno_run_context": ctx} if ctx is not None else {}
    if component_type == "agent":
        out = studio.create_agent(name=name, instructions="i", publish=True, **scope)
    elif component_type == "team":
        studio.create_agent(name=f"{name}-member", instructions="i", publish=True, **scope)
        out = studio.create_team(name=name, instructions="i", member_ids=[f"{name}-member"], publish=True, **scope)
    else:
        studio.create_agent(name=f"{name}-step", instructions="i", publish=True, **scope)
        out = studio.create_workflow(
            name=name, steps=[{"type": "step", "name": "s1", "agent_id": f"{name}-step"}], publish=True, **scope
        )
    return _data(out)["id"]


class TestRowOnlyFieldsSurviveTheToolkit:
    """description/metadata set only on the row (PATCH /components) exist in
    no config version, so no publish or rollback may clear them - there is no
    version to restore them from."""

    _EDITORS = {"agent": "edit_agent", "team": "edit_team", "workflow": "edit_workflow"}

    def _assert_survived(self, db, component_id):
        row = db.get_component(component_id)
        assert row["description"] == "operator note"
        assert row["metadata"]["team"] == "ops"

    @pytest.mark.parametrize("component_type", ["agent", "team", "workflow"])
    def test_publish_leaves_row_only_fields_alone(self, studio, db, component_type):
        component_id = _create_bare(studio, component_type, f"rowonly-{component_type}")
        _operator_patch(db, component_id)

        edit_kwargs = {"name": f"renamed-{component_type}"} if component_type == "workflow" else {"instructions": "i2"}
        _data(getattr(studio, self._EDITORS[component_type])(component_id, **edit_kwargs))
        _data(studio.publish_component(component_id))

        self._assert_survived(db, component_id)

    def test_inline_publish_leaves_row_only_fields_alone(self, studio, db):
        component_id = _create_bare(studio, "agent", "rowonly-inline")
        _operator_patch(db, component_id)

        _data(studio.edit_agent(component_id, instructions="i2", publish=True))

        self._assert_survived(db, component_id)

    def test_rollback_leaves_row_only_fields_alone(self, studio, db):
        component_id = _create_bare(studio, "agent", "rowonly-rollback")
        _data(studio.edit_agent(component_id, instructions="i2", publish=True))
        _operator_patch(db, component_id)

        _data(studio.set_current_version(component_id, 1))

        self._assert_survived(db, component_id)

    def test_async_publish_leaves_row_only_fields_alone(self, studio, db):
        component_id = _create_bare(studio, "agent", "rowonly-async")
        _operator_patch(db, component_id)
        _data(studio.edit_agent(component_id, instructions="i2"))

        _data(asyncio.run(studio.apublish_component(component_id)))

        self._assert_survived(db, component_id)

    def test_an_explicit_edit_still_overrides_the_operator(self, studio, db):
        component_id = _create_bare(studio, "agent", "rowonly-override")
        _operator_patch(db, component_id)

        _data(studio.edit_agent(component_id, description="authored", metadata={"tier": "two"}, publish=True))

        row = db.get_component(component_id)
        assert row["description"] == "authored"
        assert row["metadata"]["tier"] == "two"
        assert "team" not in row["metadata"]


class TestScopedFlowsAndTheProvenanceStamp:
    """A scoped actor's provenance stamp rides in every config's metadata, so
    stamp-only metadata must not read as "this version owns the column" - but
    a scoped caller's explicit clear still must."""

    @staticmethod
    def _ctx(user_id: str = "builder-1"):
        from agno.run import RunContext

        return RunContext(run_id="r1", session_id="s1", user_id=user_id)

    def _scoped_fixture(self, studio, db) -> str:
        ctx = self._ctx()
        created = _data(studio.create_agent(name="Scoped Bot", instructions="i", publish=True, _agno_run_context=ctx))
        component_id = created["id"]
        _operator_patch(db, component_id)
        return component_id

    def test_scoped_publish_keeps_operator_fields_beside_the_stamp(self, studio, db):
        component_id = self._scoped_fixture(studio, db)
        ctx = self._ctx()

        _data(studio.edit_agent(component_id, instructions="i2", _agno_run_context=ctx))
        _data(studio.publish_component(component_id, _agno_run_context=ctx))

        row = db.get_component(component_id)
        assert row["description"] == "operator note"
        assert row["metadata"]["team"] == "ops"

    def test_scoped_metadata_clear_still_clears(self, studio, db):
        component_id = self._scoped_fixture(studio, db)
        ctx = self._ctx()

        _data(studio.edit_agent(component_id, metadata={}, _agno_run_context=ctx, publish=True))

        metadata = db.get_component(component_id)["metadata"] or {}
        assert "team" not in metadata

    def test_scoped_description_clear_still_clears(self, studio, db):
        component_id = self._scoped_fixture(studio, db)
        ctx = self._ctx()

        _data(studio.edit_agent(component_id, description="", _agno_run_context=ctx, publish=True))

        assert not db.get_component(component_id)["description"]

    @pytest.mark.parametrize("component_type", ["agent", "team", "workflow"])
    def test_a_later_edit_does_not_revive_metadata_an_earlier_edit_cleared(self, studio, db, component_type):
        """The clear and the publish need not be the same call.

        An authored clear leaves the config carrying nothing but the
        provenance stamp, so only the marker distinguishes it from a version
        that never touched metadata. The marker lives on the config, not on
        the component, so it does not survive the rehydrate-and-reserialize an
        edit round-trips through -- and an edit of an unrelated field would
        otherwise hand the column back to the row and undo the clear.
        """
        ctx = self._ctx()
        component_id = _create_bare(studio, component_type, f"Clear {component_type}", ctx=ctx)
        _operator_patch(db, component_id)
        editor = TestRowOnlyFieldsSurviveTheToolkit._EDITORS[component_type]

        _data(getattr(studio, editor)(component_id, metadata={}, _agno_run_context=ctx))
        _data(getattr(studio, editor)(component_id, description="unrelated change", _agno_run_context=ctx))
        _data(studio.publish_component(component_id, _agno_run_context=ctx))

        metadata = db.get_component(component_id)["metadata"] or {}
        assert "team" not in metadata, "an edit after the clear handed the metadata column back to the row"

    def test_a_scoped_rollback_onto_an_authored_clear_re_clears(self, studio, db):
        component_id = self._scoped_fixture(studio, db)
        ctx = self._ctx()
        _data(studio.edit_agent(component_id, metadata={}, _agno_run_context=ctx, publish=True))
        # v1's stamp-only metadata owns nothing, so this rollback leaves the
        # row alone and the operator can re-add fields.
        _data(studio.set_current_version(component_id, 1, _agno_run_context=ctx))
        _operator_patch(db, component_id)

        # v2 carries the authored marker: rolling onto it re-clears.
        _data(studio.set_current_version(component_id, 2, _agno_run_context=ctx))

        metadata = db.get_component(component_id)["metadata"] or {}
        assert "team" not in metadata


# ----------------------------------------------------------------------
# The row sync runs after the move commits, so it cannot fail the move
# ----------------------------------------------------------------------


class TestAProjectionFailureDoesNotFailACommittedMove:
    """The catalog row is re-projected after the publish or re-point is
    durable. A projection that blows up leaves the row stale, which the next
    publish fixes; answering a hard error for a move that actually happened
    does not -- the caller retries or reports a failure that never was."""

    @staticmethod
    def _explode_projection(monkeypatch):
        """Break the projection only once the fixture is in place: the setup
        publishes too, and it must land normally."""
        import agno.db.base as db_base

        def boom(config):
            raise TypeError("projection exploded")

        monkeypatch.setattr(db_base, "project_config_identity", boom)

    @staticmethod
    def _draft(studio, db, name: str) -> str:
        component_id = _data(studio.create_agent(name=name, instructions="be", publish=True))["id"]
        _data(studio.edit_agent(agent_id=component_id, name=f"{name} Two", instructions="be two"))
        return component_id

    def test_set_current_version_reports_the_move_it_made(self, studio, db, monkeypatch):
        component_id = _rollback_fixture(studio, db)
        self._explode_projection(monkeypatch)

        out = _loads(studio.set_current_version(component_id, 2))

        assert out["ok"] is True, out
        assert out["status"] == "set_current"
        assert db.get_component(component_id)["current_version"] == 2
        assert any("could not be re-projected" in w for w in out["warnings"]), out

    def test_the_warning_does_not_quote_the_driver(self, studio, db, monkeypatch):
        """Warnings ride in a success envelope, so they land in the model's
        context. A raw adapter exception carries the statement, its bound
        parameters and -- on a connection error -- the URL with its
        credentials, so the warning names the failure and leaves the text in
        the log."""
        import agno.db.base as db_base

        secret = "postgresql://svc_user:hunter2@db.internal:5432/prod"

        def boom(config):
            raise RuntimeError(f"could not connect to server: {secret}")

        component_id = _rollback_fixture(studio, db)
        monkeypatch.setattr(db_base, "project_config_identity", boom)

        out = _loads(studio.set_current_version(component_id, 2))

        assert out["ok"] is True, out
        warnings = " ".join(out["warnings"])
        assert "could not be re-projected" in warnings, out
        assert "RuntimeError" in warnings, out
        assert secret not in warnings, out
        assert "hunter2" not in warnings, out

    def test_publish_component_reports_the_publish_it_made(self, studio, db, monkeypatch):
        component_id = self._draft(studio, db, "Publisher")
        self._explode_projection(monkeypatch)

        out = _loads(studio.publish_component(component_id))

        assert out["ok"] is True, out
        assert out["status"] == "published"
        assert db.get_component(component_id)["current_version"] == out["data"]["version"]
        assert any("could not be re-projected" in w for w in out["warnings"]), out

    def test_async_set_current_version_inherits_the_same_answer(self, studio, db, monkeypatch):
        component_id = _rollback_fixture(studio, db)
        self._explode_projection(monkeypatch)

        out = _loads(asyncio.run(studio.aset_current_version(component_id, 2)))

        assert out["ok"] is True, out
        assert db.get_component(component_id)["current_version"] == 2

    def test_async_publish_inherits_the_same_answer(self, studio, db, monkeypatch):
        component_id = self._draft(studio, db, "Async Publisher")
        self._explode_projection(monkeypatch)

        out = _loads(asyncio.run(studio.apublish_component(component_id)))

        assert out["ok"] is True, out
        assert db.get_component(component_id)["current_version"] == out["data"]["version"]

    def test_a_move_that_itself_fails_is_still_an_error(self, studio, db, monkeypatch):
        """Only the projection is best-effort. The write that moves the pointer
        is the operation itself, and its failure is still reported."""
        component_id = _rollback_fixture(studio, db)

        def boom(*args, **kwargs):
            raise RuntimeError("pointer write exploded")

        monkeypatch.setattr(db, "set_current_version", boom)
        assert _error(studio.set_current_version(component_id, 2))["code"] == "internal_error"

    def test_a_publish_that_itself_fails_is_still_an_error(self, studio, db, monkeypatch):
        component_id = self._draft(studio, db, "Failing Publisher")

        def boom(*args, **kwargs):
            raise RuntimeError("config write exploded")

        monkeypatch.setattr(db, "upsert_config", boom)
        assert _error(studio.publish_component(component_id))["code"] == "internal_error"

    def test_an_inline_publishing_edit_reports_the_version_it_wrote(self, studio, db, monkeypatch, caplog):
        """The publishing edit projects the row after its own config write
        commits, so the same rule holds: the version exists and is live, and an
        error here would have the caller retry and append yet another one."""
        component_id = _data(studio.create_agent(name="Inline", instructions="be", publish=True))["id"]

        def boom(*args, **kwargs):
            raise RuntimeError("row write exploded")

        monkeypatch.setattr(db, "upsert_component", boom)
        with caplog.at_level(logging.WARNING, logger="agno"):
            out = _loads(studio.edit_agent(agent_id=component_id, name="Inline Two", publish=True))

        assert out["ok"] is True, out
        assert out["data"]["version"] == 2
        assert db.get_component(component_id)["current_version"] == 2
        assert any("could not re-project" in record.message for record in caplog.records)

    def test_the_config_write_of_a_publishing_edit_is_still_an_error(self, studio, db, monkeypatch):
        component_id = _data(studio.create_agent(name="Inline Failing", instructions="be", publish=True))["id"]

        def boom(*args, **kwargs):
            raise RuntimeError("config write exploded")

        monkeypatch.setattr(db, "upsert_config", boom)
        assert _error(studio.edit_agent(agent_id=component_id, name="Nope", publish=True))["code"] == "internal_error"
