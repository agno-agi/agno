"""StudioTools.create_schedule applies the same target guard as its siblings.

The REST schedule routes and SchedulerTools decide "is this target live?" with
one shared predicate. StudioTools had its own copy, and the copy differed in
two ways that both refused legitimate schedules:

* it read only ``current_version is None``, so a bare catalog row carrying no
  configs at all -- a code-defined component that happens to have a control
  plane stub -- looked draft-only. There is nothing to publish on such a row,
  so the refusal could never be satisfied.
* it probed UNSCOPED, so another owner's draft row under the same id blocked
  the caller's own schedule and disclosed that the row exists.

And a malformed ``target_type`` is a bad argument, not a missing component:
a model branching on ``component_not_found`` retries a target_id that was
never the problem.
"""

import json
from importlib.util import find_spec
from typing import Any, Dict

import pytest

from agno.agent import Agent
from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.run import RunContext
from agno.tools.studio import StudioTools

ALICE = RunContext(run_id="run-a", session_id="sess-a", user_id="alice")
BOB = RunContext(run_id="run-b", session_id="sess-b", user_id="bob")

pytestmark = pytest.mark.skipif(
    find_spec("croniter") is None or find_spec("pytz") is None,
    reason="scheduler extras (croniter, pytz) not installed",
)


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="studio-schedule-guard-db", db_file=str(tmp_path / "schedule_guard.db"))


@pytest.fixture
def registry(db):
    return Registry(name="Schedule Registry", models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])


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


def _create_schedule(studio, **overrides) -> str:
    params = {
        "name": "daily-news",
        "cron": "0 9 * * *",
        "target_type": "agent",
        "target_id": "news-agent",
        "message": "Send the news.",
    }
    params.update(overrides)
    return studio.create_schedule(**params)


class TestConfiglessCatalogRowsStaySchedulable:
    def test_a_code_defined_target_with_a_bare_catalog_row_is_scheduled(self, registry, db):
        # A components row with no configs is not a draft: there is nothing to
        # publish, and the agent it names is code-defined and live.
        db.upsert_component(component_id="news-agent", component_type=ComponentType.AGENT, name="news-agent")
        assert db.get_component("news-agent")["current_version"] is None
        assert db.list_configs("news-agent", include_config=False) == []

        live = Agent(id="news-agent", name="News", model=OpenAIResponses(id="gpt-5.5"))
        studio = StudioTools(registry=registry, db=db, include_agents=[live], schedules=True)

        data = _data(_create_schedule(studio))
        assert data["endpoint"] == "/agents/news-agent/runs"
        assert data["target"]["source"] == "db"

    def test_a_real_draft_only_target_is_still_refused(self, registry, db):
        studio = StudioTools(registry=registry, db=db, schedules=True)
        _data(studio.create_agent(name="news-agent", instructions="i"))
        assert db.list_configs("news-agent", include_config=False) != []

        error = _error(_create_schedule(studio))
        assert error["code"] == "target_not_published"
        assert error["details"]["target_id"] == "news-agent"


class TestThePublishedProbeIsOwnerScoped:
    def test_another_owners_draft_row_does_not_block_or_leak(self, registry, db):
        # Bob owns a private draft-only component whose id collides with Alice's
        # code-defined agent.
        bob = StudioTools(registry=registry, db=db)
        _data(bob.create_agent(name="news-agent", instructions="bob", _agno_run_context=BOB))
        assert db.get_component("news-agent")["user_id"] == "bob"

        alice_agent = Agent(id="news-agent", name="News", model=OpenAIResponses(id="gpt-5.5"))
        studio = StudioTools(registry=registry, db=db, include_agents=[alice_agent], schedules=True)

        data = _data(_create_schedule(studio, _agno_run_context=ALICE))
        assert data["endpoint"] == "/agents/news-agent/runs"
        # Bob's row is neither read for the payload nor named in the answer.
        assert data["target"]["source"] == "code"

    def test_the_owners_own_draft_row_still_blocks(self, registry, db):
        studio = StudioTools(registry=registry, db=db, schedules=True)
        _data(studio.create_agent(name="news-agent", instructions="i", _agno_run_context=BOB))

        error = _error(_create_schedule(studio, _agno_run_context=BOB))
        assert error["code"] == "target_not_published"


class TestMalformedArgumentsKeepTheirOwnCode:
    @pytest.mark.parametrize("bad_type", ["agnet", "", None])
    def test_a_bad_target_type_is_an_invalid_request(self, registry, db, bad_type):
        studio = StudioTools(registry=registry, db=db, schedules=True)
        _data(studio.create_agent(name="news-agent", instructions="i", publish=True))

        error = _error(_create_schedule(studio, target_type=bad_type))
        assert error["code"] == "invalid_request"
        assert "Invalid target_type" in error["message"]

    def test_a_missing_target_is_still_component_not_found(self, registry, db):
        studio = StudioTools(registry=registry, db=db, schedules=True)

        error = _error(_create_schedule(studio, target_id="ghost"))
        assert error["code"] == "component_not_found"
        assert "Agent not found: ghost" in error["message"]
