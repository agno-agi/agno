"""A stored config cannot claim which version a run started on.

``agno_component_version`` is written by the run-start routes when a caller
pins a version explicitly, and read back by the lifecycle routes so a paused
run continues on the SAME version. Component metadata is merged OVER
call-site metadata, so a config carrying that key would both forge a stamp
onto runs that were never pinned and overwrite the one the route just wrote.

Configs are user-supplied and round-trip through the catalog, so the key is
stripped where it enters the object.
"""

import pytest

from agno.agent.agent import Agent
from agno.db.base import ComponentType
from agno.db.schemas.scheduler import COMPONENT_VERSION_METADATA_KEY, strip_reserved_run_metadata
from agno.db.sqlite import SqliteDb
from agno.team.team import Team
from agno.workflow.workflow import Workflow


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="reserved-db", db_file=str(tmp_path / "reserved.db"))


class TestTheHelper:
    def test_the_reserved_key_is_removed(self):
        assert strip_reserved_run_metadata({COMPONENT_VERSION_METADATA_KEY: 7, "team": "growth"}) == {"team": "growth"}

    def test_a_metadata_of_only_the_reserved_key_becomes_none(self):
        assert strip_reserved_run_metadata({COMPONENT_VERSION_METADATA_KEY: 7}) is None

    def test_other_metadata_is_untouched(self):
        assert strip_reserved_run_metadata({"team": "growth"}) == {"team": "growth"}

    def test_non_dicts_pass_through(self):
        assert strip_reserved_run_metadata(None) is None
        assert strip_reserved_run_metadata("nope") == "nope"


class TestTheKeyCannotRideAStoredConfig:
    def _stored(self, db, component_id, component_type, config):
        db.create_component_with_config(
            component_id=component_id,
            component_type=component_type,
            name=component_id,
            config=config,
            stage="published",
        )

    def test_an_agent_config_cannot_carry_it(self, db):
        self._stored(
            db,
            "forger",
            ComponentType.AGENT,
            {"name": "forger", "metadata": {COMPONENT_VERSION_METADATA_KEY: 99, "team": "growth"}},
        )
        agent = Agent.from_dict(db.get_config("forger")["config"])
        assert agent.metadata == {"team": "growth"}

    def test_a_team_config_cannot_carry_it(self, db):
        self._stored(
            db,
            "forger-team",
            ComponentType.TEAM,
            {"name": "forger-team", "members": [], "metadata": {COMPONENT_VERSION_METADATA_KEY: 99}},
        )
        team = Team.from_dict(db.get_config("forger-team")["config"])
        assert team.metadata is None

    def test_a_workflow_config_cannot_carry_it(self, db):
        self._stored(
            db,
            "forger-flow",
            ComponentType.WORKFLOW,
            {"name": "forger-flow", "steps": [], "metadata": {COMPONENT_VERSION_METADATA_KEY: 99, "k": "v"}},
        )
        workflow = Workflow.from_dict(db.get_config("forger-flow")["config"])
        assert workflow.metadata == {"k": "v"}
