"""A link names a version, and visibility is not readable depth.

Publishing shares one version of a component. A caller composing that
component supplies link rows, and each row names the child version to pin.
Nothing on the write path checked that version's stage, so a scoped caller
could pin another owner's unpublished version and then read it back
through the detail routes -- the exact disclosure
``GET /components/{id}/configs/{version}`` refuses to the same caller.

The refusal here is that route's, verbatim, so neither becomes an oracle
for the other.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings
from agno.prompt import Prompt
from agno.prompt.prompt import retained_prompt_handle
from agno.team.team import Team


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="pin-db", db_file=str(tmp_path / "pin.db"))


def _client(db, user_id=None):
    app = FastAPI()

    @app.middleware("http")
    async def _scope(request, call_next):
        request.state.user_isolation_enabled = user_id is not None
        request.state.user_id = user_id
        request.state.scopes = []
        return await call_next(request)

    app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app)


@pytest.fixture
def alice_agent(db):
    """Published v1, plus an unpublished v2 that is alice's alone."""
    db.create_component_with_config(
        component_id="radar",
        component_type=ComponentType.AGENT,
        name="radar",
        config={"name": "radar", "instructions": "PUBLIC v1"},
        stage="published",
        user_id="alice",
    )
    db.upsert_config("radar", config={"name": "radar", "instructions": "SECRET v2"}, user_id="alice")
    return "radar"


@pytest.fixture
def bob_team(db, alice_agent):
    db.create_component_with_config(
        component_id="bob-team",
        component_type=ComponentType.TEAM,
        name="bob-team",
        config={"name": "bob-team", "members": [{"type": "agent", "agent_id": alice_agent}]},
        stage="draft",
        user_id="bob",
    )
    return "bob-team"


def _pin(child_id, version):
    return [
        {
            "link_kind": "member",
            "link_key": "member_0",
            "child_component_id": child_id,
            "child_version": version,
            "position": 0,
            "meta": {"type": "agent"},
        }
    ]


class TestPinningAnotherOwnersUnpublishedVersion:
    def test_create_config_refuses_the_pin(self, db, bob_team, alice_agent):
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 404, (r.status_code, r.text)
        assert "SECRET" not in r.text

    def test_update_config_refuses_the_pin(self, db, bob_team, alice_agent):
        r = _client(db, "bob").patch(
            f"/components/{bob_team}/configs/1",
            json={"config": {"name": "bob-team"}, "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 404, (r.status_code, r.text)

    def test_the_refusal_matches_the_direct_read(self, db, bob_team, alice_agent):
        """Neither route may become an oracle for the other."""
        client = _client(db, "bob")
        pinned = client.post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        direct = client.get(f"/components/{alice_agent}/configs/2")
        assert pinned.status_code == direct.status_code == 404
        assert pinned.json()["detail"] == direct.json()["detail"]

    def test_no_link_row_survives_the_refusal(self, db, bob_team, alice_agent):
        _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        assert db.get_links(bob_team, version=2) == []


class TestPinningAnAbsentVersionOfAnotherOwnersComponent:
    """A version with no config row must answer a foreign caller like the
    draft it may not read.

    The direct read gives that caller one 404 for a draft, a tombstoned
    version, and a version that was never created. A write path that refuses
    the draft but accepts the other two leaks one bit per version number:
    "this one is a live unpublished draft" -- the owner's work-in-progress
    high-water mark, enumerable by sweeping pins.
    """

    def test_create_config_refuses_a_nonexistent_version(self, db, bob_team, alice_agent):
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 99)},
        )
        assert r.status_code == 404, (r.status_code, r.text)
        assert db.get_links(bob_team, version=2) == []

    def test_update_config_refuses_a_nonexistent_version(self, db, bob_team, alice_agent):
        r = _client(db, "bob").patch(
            f"/components/{bob_team}/configs/1",
            json={"config": {"name": "bob-team"}, "links": _pin(alice_agent, 99)},
        )
        assert r.status_code == 404, (r.status_code, r.text)
        assert db.get_links(bob_team, version=1) == []

    def test_create_config_refuses_a_tombstoned_version(self, db, bob_team, alice_agent):
        assert db.delete_config(alice_agent, version=2) is True
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 404, (r.status_code, r.text)

    def test_update_config_refuses_a_tombstoned_version(self, db, bob_team, alice_agent):
        assert db.delete_config(alice_agent, version=2) is True
        r = _client(db, "bob").patch(
            f"/components/{bob_team}/configs/1",
            json={"config": {"name": "bob-team"}, "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 404, (r.status_code, r.text)

    def test_the_refusal_is_one_answer_across_every_withheld_state(self, db, bob_team, alice_agent):
        """Draft, tombstoned, and never-created must be byte-indistinguishable.

        The only byte allowed to vary is the version number the caller itself
        supplied, so each refusal is also compared to the direct read of the
        same version -- the route whose answer this guard mirrors verbatim.
        """
        client = _client(db, "bob")

        def _pin_response(version):
            return client.post(
                f"/components/{bob_team}/configs",
                json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, version)},
            )

        draft = _pin_response(2)  # v2 is alice's live draft
        absent = _pin_response(99)  # v99 was never created
        assert db.delete_config(alice_agent, version=2) is True
        tombstoned = _pin_response(2)  # the same v2, now tombstoned

        assert draft.status_code == absent.status_code == tombstoned.status_code == 404
        # Same version number, different withheld state: identical bytes.
        assert draft.json() == tombstoned.json()
        # Different version numbers: identical up to the caller's own input,
        # and each one verbatim what the direct read answers.
        assert draft.json()["detail"] == f"Config {alice_agent} v2 not found"
        assert absent.json()["detail"] == f"Config {alice_agent} v99 not found"
        assert absent.json()["detail"] == client.get(f"/components/{alice_agent}/configs/99").json()["detail"]
        assert tombstoned.json()["detail"] == client.get(f"/components/{alice_agent}/configs/2").json()["detail"]

    def test_no_dangling_link_row_is_stored(self, db, bob_team, alice_agent):
        """The accepted write used to store a pin at a version that does not
        exist -- a dangling link the adapters never check for."""
        _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 99)},
        )
        for parent_version in (1, 2):
            assert db.get_links(bob_team, version=parent_version) == []


class TestTheVersionIsWhateverJsonCarried:
    """The links body is List[Dict[str, Any]], so the version arrives however
    the client typed it and the adapter's INTEGER column coerces it on the way
    in. A guard that inspects only ``int`` is walked around by quoting the
    number.
    """

    @pytest.mark.parametrize("version", ["2", 2.0, " 2 "])
    def test_a_non_int_spelling_of_the_draft_version_is_refused(self, db, bob_team, alice_agent, version):
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, version)},
        )
        assert r.status_code == 404, (version, r.status_code, r.text)
        assert db.get_links(bob_team, version=2) == []

    @pytest.mark.parametrize("version", ["1", 1.0])
    def test_a_non_int_spelling_of_a_published_version_still_works(self, db, bob_team, alice_agent, version):
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, version)},
        )
        assert r.status_code == 201, (version, r.status_code, r.text)

    @pytest.mark.parametrize(
        "version",
        [
            True,  # bool is an int subclass; the column stores it as version 1
            False,
            1.5,  # non-integral: int() truncates to 1, Postgres rounds to 2
            2.6,
            2.4,
            "2.0",  # int() raises on this string, so a skipping guard drops the link
            "2e0",
            "not-a-number",
            0,  # no version 0 exists; a stored pin at it dangles forever
            -1,
            10**12,  # outside the INTEGER column, so the guard's own read raises
        ],
    )
    def test_a_version_that_names_no_version_is_refused_outright(self, db, bob_team, alice_agent, version):
        """A guard on a caller-supplied field must refuse what it cannot read.

        Skipping is how such a guard gets walked around: every spelling here
        used to slip past the stage check and still reach the INTEGER column,
        which coerced it into a real version -- ``true`` into 1 and ``2.6``
        into 3 -- so quoting or misspelling the number pinned a version the
        caller was refused when it asked plainly.
        """
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, version)},
        )
        assert r.status_code == 400, (version, r.status_code, r.text)
        for parent_version in (1, 2):
            assert db.get_links(bob_team, version=parent_version) == [], (version, parent_version)

    def test_the_patch_route_refuses_them_too(self, db, bob_team, alice_agent):
        """The guard has two entry points and both take caller-supplied links."""
        r = _client(db, "bob").patch(
            f"/components/{bob_team}/configs/1",
            json={"config": {"name": "bob-team"}, "links": _pin(alice_agent, True)},
        )
        assert r.status_code == 400, (r.status_code, r.text)
        assert db.get_links(bob_team, version=1) == []

    def test_a_legitimate_spelling_is_stored_as_the_canonical_int(self, db, bob_team, alice_agent):
        """What the guard checked must be what the adapter stores.

        The two used to convert independently, which is the whole defect; the
        coerced value is written back so there is only one conversion.
        """
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, " 1 ")},
        )
        assert r.status_code == 201, r.text
        links = db.get_links(bob_team, version=r.json()["version"])
        assert [link["child_version"] for link in links] == [1]


class TestTheLegitimateCompositionsStillWork:
    def test_pinning_the_published_version_is_allowed(self, db, bob_team, alice_agent):
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 1)},
        )
        assert r.status_code == 201, (r.status_code, r.text)

    def test_the_owner_may_pin_their_own_draft(self, db, alice_agent):
        db.create_component_with_config(
            component_id="alice-team",
            component_type=ComponentType.TEAM,
            name="alice-team",
            config={"name": "alice-team"},
            stage="draft",
            user_id="alice",
        )
        r = _client(db, "alice").post(
            "/components/alice-team/configs",
            json={"config": {"name": "alice-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 201, (r.status_code, r.text)

    def test_the_owner_may_pin_their_own_nonexistent_version(self, db, alice_agent):
        """Dangling pins on your own component are the adapter's business;
        the not-found refusal exists only for callers the version is withheld
        from."""
        db.create_component_with_config(
            component_id="alice-team",
            component_type=ComponentType.TEAM,
            name="alice-team",
            config={"name": "alice-team"},
            stage="draft",
            user_id="alice",
        )
        r = _client(db, "alice").post(
            "/components/alice-team/configs",
            json={"config": {"name": "alice-team"}, "stage": "draft", "links": _pin(alice_agent, 99)},
        )
        assert r.status_code == 201, (r.status_code, r.text)

    def test_an_unscoped_caller_is_not_gated(self, db, bob_team, alice_agent):
        r = _client(db).post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 201, (r.status_code, r.text)


# ---------------------------------------------------------------------------
# Prompt references through the generic component routes
#
# An Agent or Team config references a Prompt as {"prompt_id": ..., "version": ...}.
# The routes derive one "prompt" link row per reference, exactly as the SDK save
# does: an omitted selector pins the current published version and the stored
# reference records that integer; "latest" stays "latest" in the config and
# NULL in the row; fallback text lives in link.meta only. Every target must be
# a published Prompt version, whoever the caller is.
# ---------------------------------------------------------------------------


def _publish(db, content="one", prompt_id="support"):
    return Prompt(id=prompt_id, content=content).save(db=db)


def _prompt_rows(db, component_id, version):
    rows = [link for link in db.get_links(component_id, version=version) if link["link_kind"] == "prompt"]
    return [
        (
            link["link_key"],
            link["child_component_id"],
            link["child_version"],
            link["position"],
            (link.get("meta") or {}).get("fallback"),
        )
        for link in sorted(rows, key=lambda link: link["position"])
    ]


def _prompt_link(prompt_id, version, *, key="instructions", fallback=None):
    link = {
        "link_kind": "prompt",
        "link_key": key,
        "child_component_id": prompt_id,
        "child_version": version,
        "position": 0 if key == "system_message" else 1,
    }
    if fallback is not None:
        link["meta"] = {"fallback": fallback}
    return link


def _agent_body(fields, *, component_id="helper", stage="published"):
    return {
        "name": component_id,
        "component_id": component_id,
        "component_type": "agent",
        "config": {"name": component_id, **fields},
        "stage": stage,
    }


def _create_agent_row(db, fields, *, component_id="helper", stage="published", links=None, user_id=None):
    db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType.AGENT,
        name=component_id,
        config={"name": component_id, **fields},
        stage=stage,
        links=links,
        user_id=user_id,
    )
    return component_id


def _create_member(db, component_id="member"):
    db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType.AGENT,
        name=component_id,
        config={"name": component_id, "instructions": "Help the team."},
        stage="published",
    )
    return component_id


class TestPromptComponentsThroughGenericCrud:
    def test_a_prompt_is_created_listed_read_and_versioned_through_the_generic_routes(self, db):
        client = _client(db)
        created = client.post(
            "/components",
            json={
                "name": "Support",
                "component_id": "support",
                "component_type": "prompt",
                "config": {"type": "prompt", "id": "support", "content": "one"},
                "stage": "published",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["component_type"] == "prompt"
        listed = client.get("/components", params={"component_type": "prompt"})
        assert [row["component_id"] for row in listed.json()["data"]] == ["support"]
        assert client.get("/components/support").json()["component_type"] == "prompt"
        second = client.post(
            "/components/support/configs",
            json={"config": {"type": "prompt", "id": "support", "content": "two"}, "stage": "published"},
        )
        assert second.status_code == 201, second.text
        assert second.json()["version"] == 2
        assert Prompt.load("support", db=db).content == "two"
        assert Prompt.load("support", db=db, version=1).content == "one"


class TestPromptLinksAreDerivedFromConfigReferences:
    @pytest.mark.parametrize(
        "selector, child_version, stored",
        [(None, 2, 2), (1, 1, 1), ("latest", None, "latest")],
        ids=["omitted-pins-current", "integer-pin", "latest-floats"],
    )
    def test_create_component_derives_an_agent_link(self, db, selector, child_version, stored):
        _publish(db, "one")
        _publish(db, "two")
        reference = {"prompt_id": "support"} if selector is None else {"prompt_id": "support", "version": selector}
        r = _client(db).post("/components", json=_agent_body({"instructions": reference}))
        assert r.status_code == 201, r.text
        assert _prompt_rows(db, "helper", 1) == [("instructions", "support", child_version, 1, None)]
        assert db.get_config("helper", version=1)["config"]["instructions"] == {
            "prompt_id": "support",
            "version": stored,
        }

    @pytest.mark.parametrize(
        "selector, child_version, stored",
        [(None, 2, 2), (1, 1, 1), ("latest", None, "latest")],
        ids=["omitted-pins-current", "integer-pin", "latest-floats"],
    )
    def test_create_config_derives_both_fields(self, db, selector, child_version, stored):
        _publish(db, "one")
        _publish(db, "two")
        _publish(db, "Old text.", prompt_id="sm")
        _create_agent_row(db, {"instructions": "plain"}, stage="draft")
        reference = {"prompt_id": "support"} if selector is None else {"prompt_id": "support", "version": selector}
        r = _client(db).post(
            "/components/helper/configs",
            json={
                "config": {
                    "name": "helper",
                    "instructions": reference,
                    "system_message": {"prompt_id": "sm", "version": "latest"},
                },
                "stage": "published",
            },
        )
        assert r.status_code == 201, r.text
        assert _prompt_rows(db, "helper", 2) == [
            ("system_message", "sm", None, 0, None),
            ("instructions", "support", child_version, 1, None),
        ]
        stored_config = db.get_config("helper", version=2)["config"]
        assert stored_config["instructions"] == {"prompt_id": "support", "version": stored}
        assert stored_config["system_message"] == {"prompt_id": "sm", "version": "latest"}

    def test_update_config_derives_the_link_for_a_draft(self, db):
        _publish(db, "one")
        _create_agent_row(db, {"instructions": "plain"}, stage="draft")
        r = _client(db).patch(
            "/components/helper/configs/1",
            json={"config": {"name": "helper", "instructions": {"prompt_id": "support"}}},
        )
        assert r.status_code == 200, r.text
        assert _prompt_rows(db, "helper", 1) == [("instructions", "support", 1, 1, None)]
        assert db.get_config("helper", version=1)["config"]["instructions"] == {"prompt_id": "support", "version": 1}

    def test_the_pin_holds_and_latest_floats_on_the_next_sdk_load(self, db):
        _publish(db, "one")
        _publish(db, "Old text.", prompt_id="sm")
        r = _client(db).post(
            "/components",
            json=_agent_body(
                {"instructions": {"prompt_id": "support"}, "system_message": {"prompt_id": "sm", "version": "latest"}}
            ),
        )
        assert r.status_code == 201, r.text
        _publish(db, "two")
        _publish(db, "New text.", prompt_id="sm")
        loaded = Agent.load("helper", db=db, strict=True)
        assert loaded.instructions == "one"
        assert loaded.system_message == "New text."

    def test_team_member_and_prompt_links_coexist_on_create(self, db):
        _publish(db, "one")
        member = _create_member(db)
        r = _client(db).post(
            "/components",
            json={
                "name": "crew",
                "component_id": "crew",
                "component_type": "team",
                "config": {
                    "name": "crew",
                    "members": [{"type": "agent", "agent_id": member}],
                    "instructions": {"prompt_id": "support"},
                },
                "stage": "published",
            },
        )
        assert r.status_code == 201, r.text
        rows = db.get_links("crew", version=1)
        assert sorted((link["link_kind"], link["link_key"], link["child_version"]) for link in rows) == [
            ("member", "member_0", 1),
            ("prompt", "instructions", 1),
        ]
        _publish(db, "two")
        loaded = Team.load("crew", db=db, strict=True)
        assert loaded.instructions == "one"
        assert [m.id for m in loaded.members] == [member]

    def test_team_member_and_prompt_links_coexist_on_create_config_and_update_config(self, db):
        _publish(db, "one")
        member = _create_member(db)
        db.create_component_with_config(
            component_id="crew",
            component_type=ComponentType.TEAM,
            name="crew",
            config={"name": "crew", "members": [{"type": "agent", "agent_id": member}]},
            stage="draft",
        )
        client = _client(db)
        config = {
            "name": "crew",
            "members": [{"type": "agent", "agent_id": member}],
            "instructions": {"prompt_id": "support", "version": "latest"},
        }
        created = client.post("/components/crew/configs", json={"config": config})
        assert created.status_code == 201, created.text
        assert sorted((link["link_kind"], link["child_version"]) for link in db.get_links("crew", version=2)) == [
            ("member", 1),
            ("prompt", None),
        ]
        edited = client.patch("/components/crew/configs/2", json={"config": {**config, "name": "Renamed"}})
        assert edited.status_code == 200, edited.text
        assert sorted((link["link_kind"], link["child_version"]) for link in db.get_links("crew", version=2)) == [
            ("member", 1),
            ("prompt", None),
        ]
        assert db.get_config("crew", version=2)["config"]["instructions"] == {
            "prompt_id": "support",
            "version": "latest",
        }


class TestConsumerFallbackLivesInLinkMetaOnly:
    def test_explicit_links_carry_the_fallback_into_link_meta_and_nowhere_else(self, db):
        _publish(db, "one")
        _create_agent_row(db, {"instructions": "plain"}, stage="draft")
        r = _client(db).post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support"}},
                "stage": "published",
                "links": [_prompt_link("support", 1, fallback=["Answer safely."])],
            },
        )
        assert r.status_code == 201, r.text
        assert _prompt_rows(db, "helper", 2) == [("instructions", "support", 1, 1, ["Answer safely."])]
        assert db.get_config("support", version=1)["config"] == {"type": "prompt", "id": "support", "content": "one"}
        assert "fallback" not in db.get_config("helper", version=2)["config"]["instructions"]
        loaded = Agent.load("helper", db=db)
        assert retained_prompt_handle(loaded, "instructions").prompt.fallback == ["Answer safely."]

    def test_an_edit_of_an_unchanged_reference_keeps_the_pin_and_the_fallback(self, db):
        _publish(db, "one")
        _publish(db, "two")
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            stage="draft",
            links=[_prompt_link("support", 1, fallback=["Answer safely."])],
        )
        r = _client(db).patch(
            "/components/helper/configs/1",
            json={"config": {"name": "Renamed", "instructions": {"prompt_id": "support", "version": 1}}},
        )
        assert r.status_code == 200, r.text
        assert _prompt_rows(db, "helper", 1) == [("instructions", "support", 1, 1, ["Answer safely."])]
        assert db.get_config("helper", version=1)["config"]["name"] == "Renamed"

    def test_a_new_version_written_from_the_current_one_keeps_the_fallback(self, db):
        _publish(db, "one")
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            links=[_prompt_link("support", 1, fallback=["Answer safely."])],
        )
        r = _client(db).post(
            "/components/helper/configs",
            json={
                "config": {"name": "Renamed", "instructions": {"prompt_id": "support", "version": 1}},
                "stage": "published",
            },
        )
        assert r.status_code == 201, r.text
        assert _prompt_rows(db, "helper", 2) == [("instructions", "support", 1, 1, ["Answer safely."])]

    def test_the_fallback_is_not_copied_to_a_different_prompt(self, db):
        _publish(db, "one")
        _publish(db, "other text", prompt_id="other")
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            links=[_prompt_link("support", 1, fallback=["Answer safely."])],
        )
        r = _client(db).post(
            "/components/helper/configs",
            json={"config": {"name": "helper", "instructions": {"prompt_id": "other"}}, "stage": "published"},
        )
        assert r.status_code == 201, r.text
        assert _prompt_rows(db, "helper", 2) == [("instructions", "other", 1, 1, None)]

    def test_a_removed_reference_is_not_resurrected(self, db):
        _publish(db, "one")
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            links=[_prompt_link("support", 1, fallback=["Answer safely."])],
        )
        r = _client(db).post(
            "/components/helper/configs",
            json={"config": {"name": "helper", "instructions": "Plain text now."}, "stage": "published"},
        )
        assert r.status_code == 201, r.text
        assert db.get_links("helper", version=2) == []


def _draft_prompt_version(db):
    db.upsert_config("support", config={"type": "prompt", "id": "support", "content": "draft"})


def _tombstoned_prompt_version(db):
    _draft_prompt_version(db)
    assert db.delete_config("support", version=2) is True


def _archived_prompt(db):
    assert db.delete_component("support") is True


_UNPUBLISHABLE = [
    pytest.param(lambda db: None, {"prompt_id": "missing"}, "not an active Prompt component", id="missing"),
    pytest.param(_draft_prompt_version, {"prompt_id": "support", "version": 2}, "which is not published", id="draft"),
    pytest.param(_archived_prompt, {"prompt_id": "support"}, "not an active Prompt component", id="archived"),
    pytest.param(
        _tombstoned_prompt_version, {"prompt_id": "support", "version": 2}, "which is not published", id="tombstoned"
    ),
]


class TestUnpublishableTargetsAreRefusedBeforeAnyWrite:
    @pytest.mark.parametrize("prepare, reference, message", _UNPUBLISHABLE)
    def test_create_component_refuses(self, db, prepare, reference, message):
        _publish(db, "one")
        prepare(db)
        r = _client(db).post("/components", json=_agent_body({"instructions": reference}))
        assert r.status_code == 400, (r.status_code, r.text)
        assert message in r.json()["detail"]
        assert db.get_component("helper") is None

    @pytest.mark.parametrize("prepare, reference, message", _UNPUBLISHABLE)
    def test_create_config_refuses(self, db, prepare, reference, message):
        _publish(db, "one")
        prepare(db)
        _create_agent_row(db, {"instructions": "plain"})
        r = _client(db).post(
            "/components/helper/configs",
            json={"config": {"name": "helper", "instructions": reference}, "stage": "published"},
        )
        assert r.status_code == 400, (r.status_code, r.text)
        assert message in r.json()["detail"]
        assert [row["version"] for row in db.list_configs("helper")] == [1]
        assert db.get_links("helper", version=2) == []

    @pytest.mark.parametrize("prepare, reference, message", _UNPUBLISHABLE)
    def test_update_config_refuses(self, db, prepare, reference, message):
        _publish(db, "one")
        prepare(db)
        _create_agent_row(db, {"instructions": "plain"}, stage="draft")
        r = _client(db).patch(
            "/components/helper/configs/1", json={"config": {"name": "helper", "instructions": reference}}
        )
        assert r.status_code == 400, (r.status_code, r.text)
        assert message in r.json()["detail"]
        assert db.get_config("helper", version=1)["config"]["instructions"] == "plain"
        assert db.get_links("helper", version=1) == []

    @pytest.mark.parametrize(
        "reference",
        [{"prompt_id": 5}, {"prompt_id": "support", "version": 0}, {"prompt_id": "support", "version": "current"}],
    )
    def test_a_malformed_reference_is_refused(self, db, reference):
        _publish(db, "one")
        r = _client(db).post("/components", json=_agent_body({"instructions": reference}))
        assert r.status_code == 400, (r.status_code, r.text)
        assert db.get_component("helper") is None

    def test_a_prompt_that_no_longer_has_a_published_version_is_refused_for_latest(self, db):
        """`latest` links follow the current version, and there has to be one to follow."""
        db.create_component_with_config(
            component_id="support",
            component_type=ComponentType.PROMPT,
            name="support",
            config={"type": "prompt", "id": "support", "content": "draft only"},
            stage="draft",
        )
        r = _client(db).post(
            "/components", json=_agent_body({"instructions": {"prompt_id": "support", "version": "latest"}})
        )
        assert r.status_code == 400, (r.status_code, r.text)
        assert "no published version" in r.json()["detail"]


class TestOwnerPrivilegeDoesNotBypassPublishedOnly:
    """A member pin may name the owner's own draft; a Prompt link may not."""

    @pytest.fixture
    def alice_prompt(self, db):
        db.create_component_with_config(
            component_id="support",
            component_type=ComponentType.PROMPT,
            name="support",
            config={"type": "prompt", "id": "support", "content": "one"},
            stage="published",
            user_id="alice",
        )
        db.upsert_config("support", config={"type": "prompt", "id": "support", "content": "draft"}, user_id="alice")
        _create_agent_row(db, {"instructions": "plain"}, stage="draft", user_id="alice")
        return "support"

    def test_the_owner_may_not_pin_their_own_draft_by_reference(self, db, alice_prompt):
        r = _client(db, "alice").post(
            "/components/helper/configs",
            json={"config": {"name": "helper", "instructions": {"prompt_id": alice_prompt, "version": 2}}},
        )
        assert r.status_code == 400, (r.status_code, r.text)
        assert "not published" in r.json()["detail"]
        assert [row["version"] for row in db.list_configs("helper")] == [1]

    def test_the_owner_may_not_pin_their_own_draft_by_explicit_link(self, db, alice_prompt):
        r = _client(db, "alice").post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": alice_prompt, "version": 2}},
                "links": [_prompt_link(alice_prompt, 2)],
            },
        )
        assert r.status_code == 400, (r.status_code, r.text)
        assert [row["version"] for row in db.list_configs("helper")] == [1]

    def test_an_unscoped_caller_is_held_to_the_same_rule(self, db, alice_prompt):
        r = _client(db).post(
            "/components/helper/configs",
            json={"config": {"name": "helper"}, "links": [_prompt_link(alice_prompt, 2)]},
        )
        assert r.status_code == 400, (r.status_code, r.text)

    def test_a_foreign_caller_still_gets_the_direct_read_refusal(self, db, alice_prompt):
        """The existing not-found answer for withheld versions is unchanged."""
        _create_agent_row(db, {"instructions": "plain"}, component_id="bob-agent", stage="draft", user_id="bob")
        r = _client(db, "bob").post(
            "/components/bob-agent/configs",
            json={"config": {"name": "bob-agent"}, "links": [_prompt_link(alice_prompt, 2)]},
        )
        assert r.status_code == 404, (r.status_code, r.text)


class TestExplicitPromptLinksStayAuthoritative:
    def test_a_caller_supplied_prompt_link_is_stored_as_sent_after_normalization(self, db):
        _publish(db, "one")
        _publish(db, "two")
        _create_agent_row(db, {"instructions": "plain"}, stage="draft")
        r = _client(db).post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support", "version": 1}},
                "stage": "published",
                "links": [_prompt_link("support", "1")],
            },
        )
        assert r.status_code == 201, r.text
        assert _prompt_rows(db, "helper", 2) == [("instructions", "support", 1, 1, None)]
        assert Agent.load("helper", db=db, strict=True).instructions == "one"

    def test_an_explicit_link_set_is_the_whole_set(self, db):
        """Explicit links replace derivation entirely, exactly as they do for members."""
        _publish(db, "one")
        member = _create_member(db)
        db.create_component_with_config(
            component_id="crew",
            component_type=ComponentType.TEAM,
            name="crew",
            config={"name": "crew", "members": [{"type": "agent", "agent_id": member}]},
            stage="draft",
        )
        r = _client(db).post(
            "/components/crew/configs",
            json={
                "config": {
                    "name": "crew",
                    "members": [{"type": "agent", "agent_id": member}],
                    "instructions": {"prompt_id": "support", "version": 1},
                },
                "links": _pin(member, 1) + [_prompt_link("support", 1)],
            },
        )
        assert r.status_code == 201, r.text
        assert [(link["link_kind"], link["child_version"]) for link in db.get_links("crew", version=2)] == [
            ("member", 1),
            ("prompt", 1),
        ]

    def test_an_explicit_prompt_link_with_an_unknown_field_is_refused(self, db):
        _publish(db, "one")
        _create_agent_row(db, {"instructions": "plain"}, stage="draft")
        r = _client(db).post(
            "/components/helper/configs",
            json={"config": {"name": "helper"}, "links": [_prompt_link("support", 1, key="description")]},
        )
        assert r.status_code == 400, (r.status_code, r.text)
        assert [row["version"] for row in db.list_configs("helper")] == [1]


class TestDeletingAReferencedPromptAnswers409:
    """The generic dependency refusal reaches the route as 409, scoped as the
    adapter scopes the veto: only parents the caller can act on block, and
    those are the ones the detail may name."""

    def test_an_operator_sees_every_dependent(self, db):
        _publish(db, "one")
        _create_agent_row(
            db, {"instructions": {"prompt_id": "support", "version": 1}}, links=[_prompt_link("support", 1)]
        )
        r = _client(db).delete("/components/support")
        assert r.status_code == 409, (r.status_code, r.text)
        assert r.json()["detail"] == "Cannot delete support: referenced by helper"
        assert db.get_component("support")["deleted_at"] is None
        assert [link["child_component_id"] for link in db.get_links("helper", version=1)] == ["support"]

    def test_the_owner_is_blocked_by_their_own_parent_and_told_which(self, db):
        db.create_component_with_config(
            component_id="support",
            component_type=ComponentType.PROMPT,
            name="support",
            config={"type": "prompt", "id": "support", "content": "one"},
            stage="published",
            user_id="alice",
        )
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            component_id="alice-agent",
            links=[_prompt_link("support", 1)],
            user_id="alice",
        )
        r = _client(db, "alice").delete("/components/support")
        assert r.status_code == 409, (r.status_code, r.text)
        assert r.json()["detail"] == "Cannot delete support: referenced by alice-agent"

    def test_another_owners_draft_parent_neither_vetoes_nor_appears(self, db):
        db.create_component_with_config(
            component_id="support",
            component_type=ComponentType.PROMPT,
            name="support",
            config={"type": "prompt", "id": "support", "content": "one"},
            stage="published",
            user_id="alice",
        )
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            component_id="bob-draft",
            stage="draft",
            links=[_prompt_link("support", 1)],
            user_id="bob",
        )
        r = _client(db, "alice").delete("/components/support")
        assert r.status_code == 204, (r.status_code, r.text)
        assert db.get_component("support") is None


class TestTwoEditCyclesOnTheSameComponent:
    """The same component, client and database through two full edit cycles:
    the pin and the fallback have to survive the second generation as well
    as the first, carried from the version each cycle supersedes."""

    def test_the_pin_and_fallback_survive_two_generations(self, db):
        _publish(db, "one")
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            links=[_prompt_link("support", 1, fallback=["Answer safely."])],
        )
        client = _client(db)
        for generation, name in ((2, "second"), (3, "third")):
            stored = db.get_config("helper", version=generation - 1)["config"]
            draft = client.post("/components/helper/configs", json={"config": {**stored, "name": name}})
            assert draft.status_code == 201, draft.text
            assert draft.json()["version"] == generation
            edited = client.patch(
                f"/components/helper/configs/{generation}", json={"config": {**stored, "name": f"{name}-edited"}}
            )
            assert edited.status_code == 200, edited.text
            published = client.patch(f"/components/helper/configs/{generation}", json={"stage": "published"})
            assert published.status_code == 200, published.text
            assert db.get_component("helper")["current_version"] == generation
            assert _prompt_rows(db, "helper", generation) == [("instructions", "support", 1, 1, ["Answer safely."])]
            assert db.get_config("helper", version=generation)["config"]["instructions"] == {
                "prompt_id": "support",
                "version": 1,
            }
            _publish(db, f"republished-{generation}")
            loaded = Agent.load("helper", db=db, strict=True)
            assert loaded.instructions == "one"
            assert retained_prompt_handle(loaded, "instructions").prompt.fallback == ["Answer safely."]


class TestPromptListingKeepsAStoredPromptThatSharesAnId:
    def test_the_prompt_filter_excludes_no_registry_ids(self, db):
        """The registry holds no Prompts, so a code-defined agent with the same id must not hide the stored Prompt."""
        from agno.registry import Registry

        _publish(db, "one")
        _publish(db, "two", prompt_id="other")
        app = FastAPI()
        app.include_router(
            get_components_router(
                os_db=db, registry=Registry(agents=[Agent(id="support", name="code agent")]), settings=AgnoAPISettings()
            )
        )
        listed = TestClient(app).get("/components", params={"component_type": "prompt"})
        assert sorted(row["component_id"] for row in listed.json()["data"]) == ["other", "support"]


class TestExplicitPromptLinksMustAgreeWithTheConfig:
    """The explicit set stays authoritative and whole, and its Prompt rows must
    say what the config references say. An omitted selector is normalized to
    the current published integer before the comparison; an explicit older
    integer never redefines it."""

    def _draft(self, db, fields=None):
        _create_agent_row(db, fields or {"instructions": "plain"}, stage="draft")
        return _client(db)

    def _refused(self, db, r, versions=(1,)):
        assert r.status_code == 400, (r.status_code, r.text)
        assert [row["version"] for row in db.list_configs("helper")] == list(versions)
        for version in versions:
            assert db.get_links("helper", version=version) == []
        return r.json()["detail"]

    def test_a_referenced_field_without_a_row_is_refused(self, db):
        _publish(db, "one")
        client = self._draft(db)
        r = client.post(
            "/components/helper/configs",
            json={"config": {"name": "helper", "instructions": {"prompt_id": "support", "version": 1}}, "links": []},
        )
        detail = self._refused(db, r)
        assert "instructions" in detail and "support" in detail

    def test_a_conflicting_prompt_id_is_refused(self, db):
        _publish(db, "one")
        _publish(db, "other text", prompt_id="other")
        client = self._draft(db)
        r = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support", "version": 1}},
                "links": [_prompt_link("other", 1)],
            },
        )
        assert "other" in self._refused(db, r)

    def test_a_conflicting_integer_is_refused(self, db):
        _publish(db, "one")
        _publish(db, "two")
        client = self._draft(db)
        r = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support", "version": 1}},
                "links": [_prompt_link("support", 2)],
            },
        )
        self._refused(db, r)

    @pytest.mark.parametrize(
        "selector, child_version",
        [("latest", 2), (2, None)],
        ids=["latest-reference-integer-row", "integer-reference-null-row"],
    )
    def test_latest_and_integer_are_distinct(self, db, selector, child_version):
        _publish(db, "one")
        _publish(db, "two")
        client = self._draft(db)
        r = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support", "version": selector}},
                "links": [_prompt_link("support", child_version)],
            },
        )
        self._refused(db, r)

    def test_an_omitted_selector_matches_a_row_pinning_the_current_version(self, db):
        _publish(db, "one")
        _publish(db, "two")
        _publish(db, "three")
        client = self._draft(db)
        r = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support"}},
                "stage": "published",
                "links": [_prompt_link("support", 3, fallback=["Answer safely."])],
            },
        )
        assert r.status_code == 201, r.text
        assert db.get_config("helper", version=2)["config"]["instructions"] == {"prompt_id": "support", "version": 3}
        assert _prompt_rows(db, "helper", 2) == [("instructions", "support", 3, 1, ["Answer safely."])]
        _publish(db, "four")
        loaded = Agent.load("helper", db=db, strict=True)
        assert loaded.instructions == "three"
        assert loaded.save(db=db) == 3
        assert db.get_config("helper", version=3)["config"]["instructions"] == {"prompt_id": "support", "version": 3}
        assert _prompt_rows(db, "helper", 3) == [("instructions", "support", 3, 1, ["Answer safely."])]
        assert [row["parent_component_id"] for row in db.get_dependents("support")] == ["helper", "helper"]

    def test_an_omitted_selector_does_not_accept_an_older_integer(self, db):
        _publish(db, "one")
        _publish(db, "two")
        client = self._draft(db)
        r = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support"}},
                "links": [_prompt_link("support", 1)],
            },
        )
        detail = self._refused(db, r)
        assert "version" in detail

    def test_an_omitted_selector_does_not_accept_a_null_row(self, db):
        _publish(db, "one")
        client = self._draft(db)
        r = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support"}},
                "links": [_prompt_link("support", None)],
            },
        )
        assert "latest" in self._refused(db, r)

    def test_duplicate_rows_for_one_field_are_refused(self, db):
        _publish(db, "one")
        client = self._draft(db)
        r = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support", "version": 1}},
                "links": [_prompt_link("support", 1), _prompt_link("support", 1)],
            },
        )
        self._refused(db, r)

    def test_an_orphan_row_on_a_plain_field_is_refused(self, db):
        _publish(db, "one")
        client = self._draft(db)
        r = client.post(
            "/components/helper/configs",
            json={"config": {"name": "helper", "instructions": "plain text"}, "links": [_prompt_link("support", 1)]},
        )
        self._refused(db, r)

    def test_removing_the_reference_and_the_row_together_is_accepted(self, db):
        _publish(db, "one")
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            stage="draft",
            links=[_prompt_link("support", 1)],
        )
        r = _client(db).patch(
            "/components/helper/configs/1",
            json={"config": {"name": "helper", "instructions": "plain text"}, "links": []},
        )
        assert r.status_code == 200, r.text
        assert db.get_links("helper", version=1) == []
        assert db.get_dependents("support") == []

    def test_a_links_only_patch_is_checked_against_the_stored_config(self, db):
        _publish(db, "one")
        _publish(db, "two")
        _create_agent_row(db, {"instructions": {"prompt_id": "support"}}, stage="draft")
        client = _client(db)
        refused = client.patch("/components/helper/configs/1", json={"links": [_prompt_link("support", 1)]})
        assert refused.status_code == 400, (refused.status_code, refused.text)
        assert db.get_links("helper", version=1) == []
        assert db.get_config("helper", version=1)["config"]["instructions"] == {"prompt_id": "support"}
        accepted = client.patch("/components/helper/configs/1", json={"links": [_prompt_link("support", 2)]})
        assert accepted.status_code == 200, accepted.text
        assert _prompt_rows(db, "helper", 1) == [("instructions", "support", 2, 1, None)]
        assert db.get_config("helper", version=1)["config"]["instructions"] == {"prompt_id": "support", "version": 2}

    def test_member_rows_are_not_checked_this_way(self, db):
        """The member rule stays as it is: an explicit member set wins over the config's member list."""
        _publish(db, "one")
        member = _create_member(db)
        other = _create_member(db, "other")
        db.create_component_with_config(
            component_id="crew",
            component_type=ComponentType.TEAM,
            name="crew",
            config={"name": "crew", "members": [{"type": "agent", "agent_id": member}]},
            stage="draft",
        )
        r = _client(db).patch(
            "/components/crew/configs/1",
            json={
                "config": {"name": "crew", "members": [{"type": "agent", "agent_id": member}]},
                "links": _pin(other, 1),
            },
        )
        assert r.status_code == 200, r.text
        assert [link["child_component_id"] for link in db.get_links("crew", version=1)] == [other]


class TestFallbackIsInheritedFromTheLatestVisibleVersion:
    def _published_with_fallback(self, db, fallback):
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            links=[_prompt_link("support", 1, fallback=fallback)],
        )

    def test_a_new_version_takes_the_fallback_of_the_latest_draft_not_the_published_one(self, db):
        _publish(db, "one")
        self._published_with_fallback(db, ["F1"])
        client = _client(db)
        draft = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support", "version": 1}},
                "links": [_prompt_link("support", 1, fallback=["F2"])],
            },
        )
        assert draft.status_code == 201, draft.text
        third = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "third", "instructions": {"prompt_id": "support", "version": 1}},
                "guard": {"latest_version": 2},
            },
        )
        assert third.status_code == 201, third.text
        assert _prompt_rows(db, "helper", 3) == [("instructions", "support", 1, 1, ["F2"])]

    def test_successive_drafts_keep_the_fallback(self, db):
        _publish(db, "one")
        _create_agent_row(
            db,
            {"instructions": {"prompt_id": "support", "version": 1}},
            stage="draft",
            links=[_prompt_link("support", 1, fallback=["F1"])],
        )
        client = _client(db)
        for generation in (2, 3):
            r = client.post(
                "/components/helper/configs",
                json={
                    "config": {"name": f"draft-{generation}", "instructions": {"prompt_id": "support", "version": 1}}
                },
            )
            assert r.status_code == 201, r.text
            assert _prompt_rows(db, "helper", generation) == [("instructions", "support", 1, 1, ["F1"])]
        assert db.get_component("helper")["current_version"] is None

    def test_a_changed_identity_inherits_nothing(self, db):
        _publish(db, "one")
        _publish(db, "other text", prompt_id="other")
        self._published_with_fallback(db, ["F1"])
        r = _client(db).post(
            "/components/helper/configs",
            json={"config": {"name": "helper", "instructions": {"prompt_id": "other"}}},
        )
        assert r.status_code == 201, r.text
        assert _prompt_rows(db, "helper", 2) == [("instructions", "other", 1, 1, None)]

    def test_a_stale_guard_commits_no_successor(self, db):
        _publish(db, "one")
        self._published_with_fallback(db, ["F1"])
        client = _client(db)
        assert client.post("/components/helper/configs", json={"config": {"name": "second"}}).status_code == 201
        stale = client.post(
            "/components/helper/configs",
            json={
                "config": {"name": "helper", "instructions": {"prompt_id": "support", "version": 1}},
                "guard": {"latest_version": 1},
            },
        )
        assert stale.status_code == 409, (stale.status_code, stale.text)
        assert [row["version"] for row in db.list_configs("helper")] == [2, 1]

    def test_an_adapter_without_the_latest_lookup_still_writes(self, db, monkeypatch):
        _publish(db, "one")
        self._published_with_fallback(db, ["F1"])

        def unsupported(component_id):
            raise NotImplementedError

        monkeypatch.setattr(db, "get_latest_config", unsupported)
        r = _client(db).post(
            "/components/helper/configs",
            json={"config": {"name": "helper", "instructions": {"prompt_id": "support", "version": 1}}},
        )
        assert r.status_code == 201, r.text
        assert _prompt_rows(db, "helper", 2) == [("instructions", "support", 1, 1, None)]


class TestLinksOnlyPatchLeavesTheStoredConfigAlone:
    """A PATCH that sends links and no config edits the rows only. The stored
    config is read to check the Prompt rows against it, and written back only
    when an omitted selector had to be normalized; nothing else in it moves."""

    _team_config = {
        "name": "t",
        "members": [{"type": "agent", "agent_id": "member"}],
        "db": {"id": "pin-db", "db_file": "/stale/path.db", "session_table": "custom_sessions"},
        "extra": {"nested": {"keep": True}},
    }

    def test_a_team_without_prompt_references_keeps_its_stored_config_exactly(self, db):
        member = _create_member(db)
        db.create_component_with_config(
            component_id="crew",
            component_type=ComponentType.TEAM,
            name="crew",
            config=dict(self._team_config),
            stage="draft",
        )
        r = _client(db).patch("/components/crew/configs/1", json={"links": _pin(member, 1)})
        assert r.status_code == 200, r.text
        assert db.get_config("crew", version=1)["config"] == self._team_config
        assert [link["child_component_id"] for link in db.get_links("crew", version=1)] == [member]

    def test_an_owners_links_only_update_does_not_revalidate_stored_references(self, db):
        """As on main: only submitted links are checked, not the untouched stored member list."""
        db.create_component_with_config(
            component_id="bob-draft",
            component_type=ComponentType.AGENT,
            name="bob-draft",
            config={"name": "bob-draft"},
            stage="draft",
            user_id="bob",
        )
        db.create_component_with_config(
            component_id="alice-team",
            component_type=ComponentType.TEAM,
            name="alice-team",
            config={"name": "alice-team", "members": [{"type": "agent", "agent_id": "bob-draft"}]},
            stage="draft",
            user_id="alice",
        )
        client = _client(db, "alice")
        assert client.patch("/components/alice-team/configs/1", json={"links": []}).status_code == 200
        # A submitted link is still held to the existing checks.
        refused = client.patch("/components/alice-team/configs/1", json={"links": _pin("bob-draft", 1)})
        assert refused.status_code == 404, (refused.status_code, refused.text)
        assert db.get_links("alice-team", version=1) == []

    def test_a_normalized_selector_is_persisted_with_everything_else_untouched(self, db):
        _publish(db, "one")
        _publish(db, "two")
        stored = {
            "name": "helper",
            "description": "keep me",
            "metadata": {"nested": {"k": 1}},
            "instructions": {"prompt_id": "support"},
        }
        _create_agent_row(db, {k: v for k, v in stored.items() if k != "name"}, stage="draft")
        r = _client(db).patch("/components/helper/configs/1", json={"links": [_prompt_link("support", 2)]})
        assert r.status_code == 200, r.text
        assert db.get_config("helper", version=1)["config"] == {
            **stored,
            "instructions": {"prompt_id": "support", "version": 2},
        }
        assert _prompt_rows(db, "helper", 1) == [("instructions", "support", 2, 1, None)]

    def test_a_refused_prompt_row_leaves_config_and_rows_exactly_as_stored(self, db):
        _publish(db, "one")
        _publish(db, "two")
        stored = {"name": "helper", "metadata": {"nested": {"k": 1}}, "instructions": {"prompt_id": "support"}}
        _create_agent_row(
            db, {k: v for k, v in stored.items() if k != "name"}, stage="draft", links=[_prompt_link("support", 2)]
        )
        r = _client(db).patch("/components/helper/configs/1", json={"links": [_prompt_link("support", 1)]})
        assert r.status_code == 400, (r.status_code, r.text)
        assert db.get_config("helper", version=1)["config"] == stored
        assert _prompt_rows(db, "helper", 1) == [("instructions", "support", 2, 1, None)]
