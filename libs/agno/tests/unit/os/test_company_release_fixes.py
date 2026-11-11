"""Company fixes before 3.2: one section per finding, each with the healthy case next to the refusal."""

import pytest

from agno.company.declarations import AutoAccept
from agno.company.routines import _DECLARED, _policy_fingerprint
from agno.run.authorization import AUTHORIZATION_KEY
from tests.unit.os.test_company_policy_path import (
    SCOPES,
    PolicySystem,
    chat,
    turn_off,
    turn_on,
    waiting,
)
from tests.unit.os.test_mini_agent_tasks import headers

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")


@pytest.fixture
def system(tmp_path):
    """A deployment with authorization on."""
    value = PolicySystem(tmp_path)
    yield value
    value.db.close()


@pytest.fixture
def open_system(tmp_path):
    """A deployment with authorization off."""
    value = PolicySystem(tmp_path, authorization=False)
    yield value
    value.db.close()


def principal(payload):
    return ((payload.get(AUTHORIZATION_KEY) or {}).get("context") or {}).get("principal_id")


# ----------------------------------------------------------------- turning auto-accept off grants nothing


def test_turning_auto_accept_off_from_chat_leaves_a_waiting_declared_routine_with_no_run_authority(system):
    product_id, routine_id = system.declare(auto_accept=True)
    assert AUTHORIZATION_KEY not in system.stored(routine_id)

    assert turn_off(system, routine_id).startswith("Auto-accept is off")
    after = system.stored(routine_id)
    assert after["metadata"]["auto_accept"] is False and "_agno_company_acceptance" not in after
    # No person confirmed anything, so the Routine does not start running under the chatting person.
    assert AUTHORIZATION_KEY not in after


@pytest.mark.parametrize("surface", ["chat", "api"])
def test_turning_auto_accept_off_keeps_the_run_authority_of_the_person_who_authored_the_routine(system, surface):
    product_id, _ = system.declare(auto_accept=False)
    created = system.api_routine(product_id, {"default_executor": "writer"}, name="authored")
    assert created.status_code == 201, created.text
    routine_id = created.json()["id"]
    before = system.stored(routine_id)
    assert principal(before) == "alice" and before["_agno_company_acceptance"]["user_id"] == "alice"

    if surface == "chat":
        assert turn_off(system, routine_id, chat(user="bob"), routine="authored").startswith("Auto-accept is off")
    else:
        path = f"/company/routines/{routine_id}"
        patched = system.client.patch(path, json={"auto_accept": False}, headers=headers(SCOPES, user="bob"))
        assert patched.status_code == 200, patched.text
    after = system.stored(routine_id)
    assert after["metadata"]["auto_accept"] is False and "_agno_company_acceptance" not in after
    assert after[AUTHORIZATION_KEY] == before[AUTHORIZATION_KEY]


def test_turning_auto_accept_off_twice_grants_nothing(system):
    product_id, routine_id = system.declare(auto_accept=False)
    before = system.stored(routine_id)
    assert turn_off(system, routine_id).startswith("Auto-accept is off")
    assert system.stored(routine_id) == before


def test_a_person_who_may_not_run_the_executor_can_still_turn_auto_accept_off(system):
    product_id, routine_id = system.declare(auto_accept=False)
    assert turn_on(system, routine_id).startswith("Auto-accept is on")
    without = [scope for scope in SCOPES if not scope.startswith("agents:")]
    assert turn_off(system, routine_id, chat(scopes=without, user="bob")).startswith("Auto-accept is off")
    after = system.stored(routine_id)
    assert after["metadata"]["auto_accept"] is False and principal(after) == "alice"


def test_turning_auto_accept_on_and_editing_instructions_still_take_the_editors_authority(system):
    product_id, routine_id = system.declare(auto_accept=False)
    assert turn_on(system, routine_id, chat(user="bob")).startswith("Auto-accept is on")
    assert principal(system.stored(routine_id)) == "bob"
    path = f"/company/routines/{routine_id}"
    # Turning it off in the same request as an instructions edit is an edit of what the Routine runs.
    body = {"auto_accept": False, "instructions": "Read the Sources again."}
    assert system.client.patch(path, json=body, headers=headers(SCOPES, user="carol")).status_code == 200
    after = system.stored(routine_id)
    assert principal(after) == "carol" and after["metadata"]["auto_accept"] is False


# ----------------------------------------------------------------- an edit does not turn a declared policy on


@pytest.mark.parametrize("edit", [{"instructions": "Read the Sources again."}, {"executor_id": "writer"}])
def test_an_edit_that_does_not_set_auto_accept_leaves_a_declared_policy_waiting(system, edit):
    declared = AutoAccept(default_executor="writer", max_open=2)
    product_id, routine_id = system.declare(auto_accept=declared)
    version = _policy_fingerprint(system.db.get_schedule(routine_id))
    project, task = system.proposes(product_id, routine_id)

    path = f"/company/routines/{routine_id}"
    patched = system.client.patch(path, json=edit, headers=headers(SCOPES, user="bob"))
    assert patched.status_code == 200, patched.text
    after = system.stored(routine_id)
    # The policy is the declared one and still has no person behind it.
    assert after["_agno_company_acceptance"] == _DECLARED
    assert after["metadata"]["auto_accept"] == declared.model_dump()
    assert _policy_fingerprint(system.db.get_schedule(routine_id)) == version
    assert waiting(system) == [("intake", "docs", "writer")]

    outcome = system.outcome(system.tick(), task["id"])
    assert outcome["status"] == "skipped" and "acts only where authorization is off" in outcome["reason"], outcome
    assert system.db.get_task(task["id"])["status"] == "backlog"
    assert system.db.get_project(project["id"])["status"] == "proposed"

    # A person still turns it on with one confirmation, and it then runs under that person.
    assert "with the policy its code declares" in turn_on(system, routine_id, chat(user="carol"))
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "carol"
    system.tick()
    assert system.db.get_task(task["id"])["status"] == "in_progress"


def test_editing_a_waiting_declared_routine_does_not_need_the_permissions_its_policy_would_use(system):
    product_id, routine_id = system.declare(auto_accept=True)
    without = [scope for scope in SCOPES if scope not in ("tasks:write", "projects:write")]
    path = f"/company/routines/{routine_id}"
    patched = system.client.patch(path, json={"instructions": "Read again."}, headers=headers(without, user="bob"))
    assert patched.status_code == 200, patched.text
    assert system.stored(routine_id)["_agno_company_acceptance"] == _DECLARED


def test_an_edit_of_a_policy_a_person_set_still_needs_the_editors_own_grant(system):
    product_id, routine_id = system.declare(auto_accept=False)
    assert turn_on(system, routine_id).startswith("Auto-accept is on")
    path = f"/company/routines/{routine_id}"
    without = [scope for scope in SCOPES if scope != "tasks:write"]
    refused = system.client.patch(path, json={"instructions": "Read again."}, headers=headers(without, user="bob"))
    assert refused.status_code == 403, refused.text
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "alice"
    edited = system.client.patch(path, json={"instructions": "Read again."}, headers=headers(SCOPES, user="bob"))
    assert edited.status_code == 200, edited.text
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "bob"


def test_setting_auto_accept_on_a_declared_routine_through_the_api_gives_it_the_persons_grant(system):
    declared = AutoAccept(default_executor="writer")
    product_id, routine_id = system.declare(auto_accept=declared)
    path = f"/company/routines/{routine_id}"
    # The stored policy sent back as it is turns it on under the sender.
    sent = system.client.patch(path, json={"auto_accept": declared.model_dump()}, headers=headers(SCOPES, user="bob"))
    assert sent.status_code == 200, sent.text
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "bob"
