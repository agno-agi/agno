"""The error codes are a contract, so the same failure answers the same code.

Two divergences this pins:

* A missing COMPONENT answers ``component_not_found`` on publish, get, list,
  restore and archive, but ``version_not_found`` on set_current_version and
  delete_version -- which is also the code those two return for a real
  component with a bad version, so a caller branching on codes cannot tell the
  two apart.
* An ambiguous display name answers ``ambiguous_reference`` with
  ``details.candidates`` everywhere except edit_*, which flattened it to
  ``invalid_request`` with empty details and dropped the ids the caller needs
  to pick from.

Plus the class docstring, which a consumer reads from ``help()`` and which
must not describe the constructor's defaults backwards.
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
    return SqliteDb(id="studio-contract-db", db_file=str(tmp_path / "contract.db"))


@pytest.fixture
def registry(db):
    return Registry(name="Contract Registry", models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])


@pytest.fixture
def studio(registry, db):
    return StudioTools(registry=registry, db=db)


def _data(s: str) -> Dict[str, Any]:
    out = json.loads(s)
    assert out.get("ok") is True, out
    return out["data"]


def _error(s: str) -> Dict[str, Any]:
    out = json.loads(s)
    assert out.get("ok") is False, out
    return out["error"]


class TestAMissingComponentAlwaysSaysComponentNotFound:
    def test_set_current_version(self, studio):
        assert _error(studio.set_current_version("ghost", 1))["code"] == "component_not_found"

    def test_delete_version(self, studio):
        assert _error(studio.delete_version("ghost", 1))["code"] == "component_not_found"

    def test_async_set_current_version(self, studio):
        error = _error(asyncio.run(studio.aset_current_version("ghost", 1)))
        assert error["code"] == "component_not_found"

    def test_async_delete_version(self, studio):
        error = _error(asyncio.run(studio.adelete_version("ghost", 1)))
        assert error["code"] == "component_not_found"

    def test_it_matches_the_surfaces_that_already_got_it_right(self, studio):
        codes = {
            "publish_component": _error(studio.publish_component("ghost"))["code"],
            "get_component": _error(studio.get_component("ghost"))["code"],
            "list_versions": _error(studio.list_versions("ghost"))["code"],
            "restore_component": _error(studio.restore_component("ghost"))["code"],
            "archive_component": _error(studio.archive_component("ghost"))["code"],
            "set_current_version": _error(studio.set_current_version("ghost", 1))["code"],
            "delete_version": _error(studio.delete_version("ghost", 1))["code"],
        }
        assert set(codes.values()) == {"component_not_found"}, codes


class TestARealComponentKeepsVersionNotFound:
    def test_set_current_version_on_a_bad_version(self, studio):
        _data(studio.create_agent(name="tutor", instructions="i", publish=True))
        assert _error(studio.set_current_version("tutor", 9))["code"] == "version_not_found"

    def test_delete_version_on_a_bad_version(self, studio):
        _data(studio.create_agent(name="tutor", instructions="i", publish=True))
        assert _error(studio.delete_version("tutor", 9))["code"] == "version_not_found"

    def test_the_two_cases_are_distinguishable(self, studio):
        _data(studio.create_agent(name="tutor", instructions="i", publish=True))
        missing_component = _error(studio.set_current_version("ghost", 9))["code"]
        missing_version = _error(studio.set_current_version("tutor", 9))["code"]
        assert missing_component != missing_version


class TestAmbiguousNamesKeepTheirCandidates:
    @staticmethod
    def _twin_agents(studio) -> None:
        _data(studio.create_agent(name="Twin", instructions="a", component_id="twin-one", publish=True))
        _data(studio.create_agent(name="Twin", instructions="b", component_id="twin-two", publish=True))

    def test_edit_agent_matches_get_component(self, studio):
        self._twin_agents(studio)

        reference = _error(studio.get_component("Twin"))
        error = _error(studio.edit_agent("Twin", instructions="c"))
        assert error["code"] == reference["code"] == "ambiguous_reference"
        assert set(error["details"]["candidates"]) == {"twin-one", "twin-two"}

    def test_edit_team_matches_get_component(self, studio):
        self._twin_agents(studio)
        _data(studio.create_team(name="Duo", instructions="t", member_ids=["twin-one"], component_id="duo-one"))
        _data(studio.create_team(name="Duo", instructions="t", member_ids=["twin-two"], component_id="duo-two"))

        error = _error(studio.edit_team("Duo", instructions="z"))
        assert error["code"] == "ambiguous_reference"
        assert set(error["details"]["candidates"]) == {"duo-one", "duo-two"}

    def test_edit_workflow_matches_get_component(self, studio):
        self._twin_agents(studio)
        _data(
            studio.create_workflow(
                name="Flow",
                steps=[{"type": "step", "name": "s", "agent_id": "twin-one"}],
                component_id="flow-one",
            )
        )
        _data(
            studio.create_workflow(
                name="Flow",
                steps=[{"type": "step", "name": "s", "agent_id": "twin-two"}],
                component_id="flow-two",
            )
        )

        error = _error(studio.edit_workflow("Flow", description="z"))
        assert error["code"] == "ambiguous_reference"
        assert set(error["details"]["candidates"]) == {"flow-one", "flow-two"}

    def test_async_edit_agent_matches_the_sync_twin(self, studio):
        self._twin_agents(studio)

        error = _error(asyncio.run(studio.aedit_agent("Twin", instructions="c")))
        assert error["code"] == "ambiguous_reference"
        assert set(error["details"]["candidates"]) == {"twin-one", "twin-two"}

    def test_a_deliberate_runner_refusal_still_reads_as_invalid_request(self, registry, db):
        from agno.agent import Agent

        # A code-defined component is not editable; that refusal is prose the
        # caller can act on, and must not be swallowed by the ambiguity branch.
        live = Agent(id="live", name="Live", model=OpenAIResponses(id="gpt-5.5"))
        studio = StudioTools(registry=registry, db=db, include_agents=[live])
        assert _error(studio.edit_agent("live", instructions="x"))["code"] == "invalid_request"


class TestTheClassDocstringMatchesTheConstructor:
    def test_the_versions_default_is_described_as_it_is(self):
        import inspect

        signature = inspect.signature(StudioTools.__init__)
        assert signature.parameters["versions"].default is True

        # Reflowed to one line: the Args block wraps, so a raw substring
        # search silently matches nothing and passes whatever the text says.
        doc = " ".join((StudioTools.__doc__ or "").split())
        entry = doc.split("versions: Expose versioning tools")[1].split("list_limit:")[0]
        assert "Defaults to True" in entry, entry
        assert "Defaults to False" not in entry, entry

    def test_the_palette_parameters_are_documented(self):
        import inspect

        doc = StudioTools.__doc__ or ""
        documented = {name for name in inspect.signature(StudioTools.__init__).parameters if f"{name}:" in doc}
        assert {"allowed_tools", "denied_tools"} <= documented


class TestAStaleCatalogSchemaKeepsItsRemedy:
    """A stale catalog table is an operational condition with a fix the caller
    can apply, and the exception's message carries the command that applies it.

    These are deliberately not ValueErrors -- several routers map ValueError to
    400, which would report a stale database as a client error -- so the error
    mapper has to recognise them by type. Without that they fall through to
    `internal_error`, whose message is a fixed fallback string, and both the
    identity of the failure and its remedy are lost before the caller sees it.
    """

    @staticmethod
    def _studio():
        return StudioTools(registry=Registry(name="R", models=[OpenAIResponses(id="gpt-5.5")]))

    def test_the_envelope_names_the_condition_and_keeps_the_message(self):
        from agno.exceptions import MigrationRequiredError

        exc = MigrationRequiredError("agno_components is on an older schema; run: agno db migrate")

        out = json.loads(self._studio()._error_from_exception(exc, "Failed to create agent"))

        assert out["error"]["code"] == "db_schema_stale", out
        assert "agno db migrate" in out["error"]["message"], out

    def test_a_subclass_is_recognised_by_type_not_by_class_name(self):
        # MigrationRequiredError subclasses SchemaMismatchError; the mapper's
        # by-name table would miss any subclass, so this must match on type.
        from agno.exceptions import SchemaMismatchError

        class NarrowerSchemaProblem(SchemaMismatchError):
            pass

        out = json.loads(self._studio()._error_from_exception(NarrowerSchemaProblem("stale"), "Failed"))

        assert out["error"]["code"] == "db_schema_stale", out

    def test_the_warning_channel_keeps_it_too(self):
        # A best-effort warning rides in a SUCCESS envelope. A schema error is
        # ours and safe to name there, unlike a raw driver exception.
        from agno.exceptions import MigrationRequiredError

        warning = self._studio()._warning_from_exception(
            MigrationRequiredError("run: agno db migrate"), "row lags the live version"
        )

        assert "agno db migrate" in warning, warning
