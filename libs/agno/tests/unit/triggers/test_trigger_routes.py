"""Triggers as data: created, changed and removed over /triggers, on the sources declared in code."""

import time

import jwt
from sqlalchemy import inspect

from agno.db.base import ComponentType
from agno.db.schemas.triggers import (
    CODE_MANAGED,
    EVENT_IGNORED,
    EVENT_PENDING,
    EVENT_SUCCESS,
)
from agno.os import Authorization
from agno.registry._reserved import BUILDER_ID
from agno.triggers import Trigger, TriggerManager
from tests.unit.triggers.conftest import call, comment_payload, issue_payload

INSTRUCTION = "Triage this issue: label it and comment."
KEY = "trigger-routes-test-key-at-least-32-characters-long"


def nothing(github, agent):
    return []


def body(**overrides):
    fields = {
        "name": "triage-issues",
        "source_id": "github",
        "events": ["issues.opened"],
        "target_type": "agent",
        "target_id": "engineer",
        "input": INSTRUCTION,
    }
    fields.update(overrides)
    return fields


def checked(**options):
    authorization = Authorization(verification_keys=[KEY], algorithm="HS256", audience="test")
    return {"id": "test", "authorization": authorization, **options}


def bearer(scopes, sub="alice"):
    claims = {"sub": sub, "aud": "test", "scopes": scopes, "exp": int(time.time()) + 300}
    return {"Authorization": "Bearer " + jwt.encode(claims, KEY, algorithm="HS256")}


WRITER = ["triggers:read", "triggers:write", "triggers:delete", "agents:run", "agents:read"]


async def stored_rows(os):
    """Everything stored for triggers, to compare before and after."""
    triggers = sorted((await call(os.db, "get_triggers", limit=1000))[0], key=lambda row: row["id"])
    events = sorted((await call(os.db, "get_trigger_events", limit=1000))[0], key=lambda row: row["id"])
    return triggers, events


# ------------------------------------------------------------------------------ create and fire


async def test_a_trigger_created_over_rest_fires_for_a_matching_delivery(make_os):
    os = await make_os(nothing, os_options={"id": "the-os"})

    created = await os.client.post("/triggers", json=body(continue_on=["issue_comment.created"]))
    assert created.status_code == 201, created.text
    trigger = created.json()
    assert trigger["name"] == "triage-issues" and trigger["enabled"] is True
    assert trigger["filters"] == {"allow": "members"}
    assert trigger["os_id"] == "the-os" and trigger["managed_by"] is None

    assert (await os.deliver(issue_payload())).json()["status"] == "accepted"
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS and row["trigger_id"] == trigger["id"]
    assert os.model.inputs[0].startswith(INSTRUCTION)

    # It is listed, read by id, and its events are listed with it.
    listed = (await os.client.get("/triggers")).json()
    assert [item["id"] for item in listed["data"]] == [trigger["id"]] and listed["meta"]["total_count"] == 1
    assert (await os.client.get(f"/triggers/{trigger['id']}")).json()["input"] == INSTRUCTION
    events = (await os.client.get(f"/triggers/{trigger['id']}/events")).json()
    assert [event["status"] for event in events["data"]] == ["success"]
    # The raw payload stays in storage; the listing describes the event.
    assert "payload" not in events["data"][0]["event"] and events["data"][0]["event"]["repository"] == "agno-agi/agno"


async def test_a_trigger_cannot_be_created_on_a_source_that_is_not_declared(make_os):
    os = await make_os(nothing)

    refused = await os.client.post("/triggers", json=body(source_id="posthog"))

    assert refused.status_code == 422
    assert "Source 'posthog' is not declared on this AgentOS. Declared sources: github." in refused.json()["detail"]
    assert await stored_rows(os) == ([], [])

    # The sources that exist are listed, with the kinds each commonly sends.
    (source,) = (await os.client.get("/triggers/sources")).json()
    assert source["id"] == "github" and source["type"] == "github"
    assert "issues.opened" in source["event_kinds"] and "pull_request.opened" in source["event_kinds"]


async def test_a_filter_the_source_cannot_apply_is_refused(make_os):
    os = await make_os(nothing)

    unknown = await os.client.post("/triggers", json=body(filters={"branch": "main"}))
    assert unknown.status_code == 422 and "filters on allow and labels" in unknown.json()["detail"]
    wrong = await os.client.post("/triggers", json=body(filters={"allow": "everyone"}))
    assert wrong.status_code == 422 and 'allow must be "members" or "anyone"' in wrong.json()["detail"]

    kept = await os.client.post("/triggers", json=body(filters={"allow": "anyone", "labels": ["Agent"]}))
    assert kept.status_code == 201 and kept.json()["filters"] == {"allow": "anyone", "labels": ["agent"]}


async def test_a_name_is_taken_once(make_os):
    os = await make_os(nothing)

    assert (await os.client.post("/triggers", json=body())).status_code == 201
    again = await os.client.post("/triggers", json=body(input="Another instruction."))

    assert again.status_code == 409 and "already exists" in again.json()["detail"]
    assert len((await stored_rows(os))[0]) == 1


# ---------------------------------------------------------------------- the refusals of schedules


async def test_a_target_that_could_never_run_is_refused(make_os):
    os = await make_os(nothing)
    os.db.upsert_component("retired", component_type=ComponentType.AGENT, name="Retired")
    os.db.delete_component("retired")
    os.db.upsert_component("unfinished", component_type=ComponentType.AGENT, name="Unfinished")
    os.db.upsert_config("unfinished", config={"name": "Unfinished"})

    internal = await os.client.post("/triggers", json=body(target_id=BUILDER_ID))
    assert internal.status_code == 409
    assert internal.json()["detail"] == (
        "Manager specialists are internal. Give the trigger Super Agent as its target instead."
    )
    archived = await os.client.post("/triggers", json=body(target_id="retired"))
    assert archived.status_code == 409
    assert archived.json()["detail"] == (
        "Cannot create trigger 'triage-issues': its target agent 'retired' is archived. Restore the component first."
    )
    draft = await os.client.post("/triggers", json=body(target_id="unfinished"))
    assert draft.status_code == 409
    assert draft.json()["detail"] == (
        "Cannot create trigger 'triage-issues': its target agent 'unfinished' has no published version. "
        "Publish it first."
    )
    assert await stored_rows(os) == ([], [])

    # The same holds when a stored trigger is pointed at such a target, and when it is turned on.
    trigger = (await os.client.post("/triggers", json=body())).json()
    repointed = await os.client.patch(f"/triggers/{trigger['id']}", json={"target_id": "retired"})
    assert repointed.status_code == 409 and "is archived" in repointed.json()["detail"]
    await call(os.db, "update_trigger", trigger["id"], target_id="retired", enabled=False)
    enabled = await os.client.post(f"/triggers/{trigger['id']}/enable")
    assert enabled.status_code == 409 and "Cannot enable trigger" in enabled.json()["detail"]


# ------------------------------------------------------------------------- who may do what


async def test_a_caller_without_triggers_write_cannot_create_one(make_os):
    os = await make_os(nothing, os_options=checked())

    assert (await os.client.post("/triggers", json=body())).status_code == 401
    reader = await os.client.post("/triggers", json=body(), headers=bearer(["triggers:read", "agents:run"]))
    assert reader.status_code == 403
    # The right to write triggers is not the right to run the target.
    no_run = await os.client.post("/triggers", json=body(), headers=bearer(["triggers:write"]))
    assert no_run.status_code == 403
    assert await stored_rows(os) == ([], [])

    writer = await os.client.post("/triggers", json=body(), headers=bearer(WRITER))
    assert writer.status_code == 201, writer.text
    assert writer.json()["user_id"] == "alice"
    # What the caller may do is saved with the trigger and never shown.
    assert writer.json()["payload"] is None
    (stored,) = (await stored_rows(os))[0]
    assert stored["payload"]["_agno_authorization"]["context"]["principal_id"] == "alice"

    # Reading needs triggers:read, and deleting needs triggers:delete.
    trigger_id = writer.json()["id"]
    assert (await os.client.get("/triggers", headers=bearer(["agents:run"]))).status_code == 403
    assert (await os.client.get("/triggers/sources", headers=bearer(["triggers:read"]))).status_code == 200
    cannot_delete = await os.client.delete(f"/triggers/{trigger_id}", headers=bearer(["triggers:write"]))
    assert cannot_delete.status_code == 403
    assert (await os.client.delete(f"/triggers/{trigger_id}", headers=bearer(WRITER))).status_code == 204


async def test_with_user_isolation_a_caller_sees_and_changes_only_their_own(make_os):
    os = await make_os(nothing, os_options=checked(user_isolation=True))
    alice, bob = bearer(WRITER, sub="alice"), bearer(WRITER, sub="bob")

    mine = (await os.client.post("/triggers", json=body(), headers=alice)).json()
    assert mine["user_id"] == "alice"
    await os.deliver(issue_payload())
    await os.run_events()
    (event,) = await os.events()
    assert event["status"] == EVENT_SUCCESS and event["user_id"] == "alice"

    # Bob sees none of it.
    assert (await os.client.get("/triggers", headers=bob)).json()["data"] == []
    assert (await os.client.get("/triggers/events", headers=bob)).json()["data"] == []
    for method, path in (
        ("GET", f"/triggers/{mine['id']}"),
        ("PATCH", f"/triggers/{mine['id']}"),
        ("DELETE", f"/triggers/{mine['id']}"),
        ("POST", f"/triggers/{mine['id']}/enable"),
        ("POST", f"/triggers/{mine['id']}/disable"),
        ("GET", f"/triggers/{mine['id']}/events"),
        ("POST", f"/triggers/{mine['id']}/events/{event['id']}/replay"),
    ):
        answer = await os.client.request(
            method, path, headers=bob, json={"input": "Bob's."} if method == "PATCH" else None
        )
        assert answer.status_code == 404, (method, path, answer.text)

    # Names are each owner's own, so Bob may use the same one.
    his = (await os.client.post("/triggers", json=body(), headers=bob)).json()
    assert his["user_id"] == "bob" and his["id"] != mine["id"]

    # Alice still has hers, unchanged, and only hers.
    listed = (await os.client.get("/triggers", headers=alice)).json()["data"]
    assert [item["id"] for item in listed] == [mine["id"]] and listed[0]["input"] == INSTRUCTION
    assert [item["id"] for item in (await os.client.get("/triggers/events", headers=alice)).json()["data"]] == [
        event["id"]
    ]


# ----------------------------------------------------------------------------- change and remove


async def test_a_trigger_is_changed_disabled_and_deleted(make_os):
    os = await make_os(nothing)
    trigger = (await os.client.post("/triggers", json=body())).json()

    changed = await os.client.patch(
        f"/triggers/{trigger['id']}",
        json={"input": "Only label it.", "events": ["issues.opened", "issues.reopened"], "timeout_seconds": 120},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["input"] == "Only label it." and changed.json()["timeout_seconds"] == 120
    assert changed.json()["events"] == ["issues.opened", "issues.reopened"]
    assert (await os.client.patch(f"/triggers/{trigger['id']}", json={"name": None})).status_code == 422
    assert (await os.client.patch(f"/triggers/{trigger['id']}", json={"source_id": "posthog"})).status_code == 422

    # Disabled, an event for it starts nothing; enabled again, it does.
    off = await os.client.post(f"/triggers/{trigger['id']}/disable")
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert (await os.deliver(issue_payload())).json()["status"] == "ignored"
    on = await os.client.post(f"/triggers/{trigger['id']}/enable")
    assert on.status_code == 200 and on.json()["enabled"] is True
    assert (await os.deliver(issue_payload(number=8), delivery="d-2")).json()["status"] == "accepted"
    await os.run_events()
    assert os.model.inputs[0].startswith("Only label it.")

    assert (await os.client.delete(f"/triggers/{trigger['id']}")).status_code == 204
    assert (await os.client.get(f"/triggers/{trigger['id']}")).status_code == 404
    # Its events go with it; the one that matched no trigger stays.
    triggers, events = await stored_rows(os)
    assert triggers == [] and [event["status"] for event in events] == [EVENT_IGNORED]


# ------------------------------------------------------------------ declared in code and stored


def in_code(github, agent):
    return [Trigger(name="triage-issues", on=github.on("issues.opened"), agent=agent, input="The instruction in code.")]


async def test_a_name_declared_in_code_cannot_be_stored_and_the_code_trigger_cannot_be_changed_here(make_os):
    os = await make_os(in_code)
    (declared,) = (await os.client.get("/triggers")).json()["data"]
    assert declared["managed_by"] == CODE_MANAGED

    taken = await os.client.post("/triggers", json=body())
    assert taken.status_code == 409 and "is declared in code" in taken.json()["detail"]
    changed = await os.client.patch(f"/triggers/{declared['id']}", json={"input": "Changed over REST."})
    assert changed.status_code == 409 and "declared in code and cannot be changed here" in changed.json()["detail"]
    assert (await os.client.delete(f"/triggers/{declared['id']}")).status_code == 409
    (kept,) = (await stored_rows(os))[0]
    assert kept["input"] == "The instruction in code."

    # It can be turned off and on: a declared trigger keeps its stored state across starts.
    assert (await os.client.post(f"/triggers/{declared['id']}/disable")).json()["enabled"] is False
    await os.start()
    assert (await os.client.get(f"/triggers/{declared['id']}")).json()["enabled"] is False


async def test_code_takes_over_a_stored_trigger_of_its_name(make_os):
    before = await make_os(nothing)
    stored = (await before.client.post("/triggers", json=body(input="The stored instruction."))).json()

    # A later version of the code declares a trigger of that name.
    os = await make_os(in_code)

    (trigger,) = (await stored_rows(os))[0]
    assert trigger["id"] == stored["id"] and trigger["managed_by"] == CODE_MANAGED
    await os.deliver(issue_payload())
    await os.run_events()
    assert len(os.model.inputs) == 1 and os.model.inputs[0].startswith("The instruction in code.")


async def test_a_stored_trigger_of_another_owner_stands_aside_for_the_code_one(make_os):
    os = await make_os(in_code)
    # Stored under an owner, so it shares the name without sharing the row.
    theirs = await TriggerManager(os.db).acreate(
        name="triage-issues",
        source_id="github",
        events=["issues.opened"],
        target_type="agent",
        target_id="engineer",
        input="The stored instruction.",
        user_id="alice",
    )

    await os.deliver(issue_payload())
    await os.run_events()

    assert len(os.model.inputs) == 1 and os.model.inputs[0].startswith("The instruction in code.")
    (aside,) = await os.events(trigger_id=theirs.id)
    assert aside["status"] == EVENT_IGNORED
    assert aside["reason"] == "trigger 'triage-issues' is declared in code, and that one is used"


# --------------------------------------------------------------------------------------- replay


async def test_replay_runs_a_stored_event_again_and_records_a_second_run(make_os):
    os = await make_os(nothing)
    trigger = (await os.client.post("/triggers", json=body(continue_on=["issue_comment.created"]))).json()
    await os.deliver(issue_payload())
    await os.run_events()
    (first,) = await os.events()
    assert first["status"] == EVENT_SUCCESS

    replayed = await os.client.post(f"/triggers/{trigger['id']}/events/{first['id']}/replay")

    assert replayed.status_code == 202, replayed.text
    assert replayed.json()["status"] == EVENT_PENDING and replayed.json()["id"] != first["id"]
    await os.run_events()
    again, second = await os.events()
    # The first event keeps its record. The replay is a second event with a run of its own,
    # in the same conversation.
    assert again == first
    assert second["id"] == replayed.json()["id"] and second["status"] == EVENT_SUCCESS
    assert second["run_id"] and second["run_id"] != first["run_id"]
    assert second["session_id"] == first["session_id"]
    assert len(os.model.inputs) == 2 and os.model.inputs[1] == os.model.inputs[0]


async def test_an_event_that_cannot_be_run_again_is_refused(make_os):
    os = await make_os(nothing)
    trigger = (await os.client.post("/triggers", json=body())).json()
    other = (await os.client.post("/triggers", json=body(name="other", events=["push"]))).json()

    # Ignored: an outside account. Stored without its payload.
    await os.deliver(issue_payload(association="NONE", sender="mallory"))
    (ignored,) = await os.events()
    refused = await os.client.post(f"/triggers/{trigger['id']}/events/{ignored['id']}/replay")
    assert refused.status_code == 409 and "was ignored and stored without its payload" in refused.json()["detail"]

    # Still waiting.
    await os.deliver(issue_payload(number=8), delivery="d-2")
    waiting = (await os.events())[-1]
    refused = await os.client.post(f"/triggers/{trigger['id']}/events/{waiting['id']}/replay")
    assert refused.status_code == 409 and "is still being handled" in refused.json()["detail"]

    await os.run_events()
    done = (await os.events())[-1]
    # Not this trigger's event, and no such event.
    assert (await os.client.post(f"/triggers/{other['id']}/events/{done['id']}/replay")).status_code == 404
    assert (await os.client.post(f"/triggers/{trigger['id']}/events/te_missing/replay")).status_code == 404
    # A disabled trigger runs nothing.
    await os.client.post(f"/triggers/{trigger['id']}/disable")
    refused = await os.client.post(f"/triggers/{trigger['id']}/events/{done['id']}/replay")
    assert refused.status_code == 409 and "is disabled" in refused.json()["detail"]
    assert len(await os.events()) == 2 and len(os.model.inputs) == 1


# ---------------------------------------------------------------------------------------- reads


async def test_a_request_that_only_reads_changes_nothing(make_os):
    os = await make_os(nothing)

    # Before anything is stored, reading creates no table.
    for path in ("/triggers", "/triggers/events", "/triggers/sources", "/triggers/none", "/triggers/none/events"):
        assert (await os.client.get(path)).status_code in (200, 404)
    tables = set(inspect(os.db.db_engine).get_table_names(schema=getattr(os.db, "db_schema", None)))
    assert not {"agno_triggers", "agno_trigger_events"} & tables

    trigger = (await os.client.post("/triggers", json=body(continue_on=["issue_comment.created"]))).json()
    await os.deliver(issue_payload())
    await os.deliver(comment_payload(), event="issue_comment", delivery="d-2")
    await os.deliver(issue_payload(association="NONE", sender="mallory", number=9), delivery="d-3")
    before = await stored_rows(os)
    assert len(before[1]) == 3

    for path in (
        "/triggers",
        "/triggers?enabled=true&source_id=github",
        f"/triggers/{trigger['id']}",
        "/triggers/sources",
        "/triggers/events",
        "/triggers/events?status=pending&status=ignored",
        f"/triggers/events?trigger_id={trigger['id']}&event_key=agno-agi/agno%237",
        f"/triggers/{trigger['id']}/events",
    ):
        answer = await os.client.get(path)
        assert answer.status_code == 200, (path, answer.text)

    assert await stored_rows(os) == before
    assert os.model.inputs == []


async def test_events_are_listed_by_trigger_state_and_conversation(make_os):
    os = await make_os(nothing)
    trigger = (await os.client.post("/triggers", json=body())).json()
    await os.deliver(issue_payload())
    await os.deliver(issue_payload(association="NONE", sender="mallory", number=9), delivery="d-2")
    await os.deliver(issue_payload(), event="push", delivery="d-3")
    await os.run_events()

    everything = (await os.client.get("/triggers/events")).json()
    assert everything["meta"]["total_count"] == 3
    ignored = (await os.client.get("/triggers/events?status=ignored")).json()["data"]
    assert {event["reason"].split(" ")[0] for event in ignored} == {"mallory", "no"}
    # An event that matched no trigger has none.
    assert {event["trigger_id"] for event in ignored} == {trigger["id"], None}
    one = (await os.client.get("/triggers/events?event_key=agno-agi/agno%237&status=success")).json()["data"]
    assert len(one) == 1 and one[0]["run_id"]
