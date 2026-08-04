"""Tests for Skills integration on Team.

Verifies that:
- Skills tools are registered when team.skills is set
- Skills tools are absent when team.skills is None
- Skills system prompt snippet is injected into the system message (sync and async)
- Skills system prompt snippet is omitted when team.skills is None
- deep_copy shares the Skills instance by reference (shared resource)
- save stores skill names; load re-resolves them from the database's skills table
"""

import json
from typing import List
from unittest.mock import MagicMock

import pytest

from agno.models.base import Function
from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.skills import DbSkills, LocalSkills, Skills
from agno.skills.executor import SkillExecutor
from agno.team._messages import aget_system_message, get_system_message
from agno.team._tools import _determine_tools_for_model
from agno.team.team import Team, get_team_by_id

SAMPLE_SKILLS_DIR = "cookbook/02_agents/16_skills/sample_skills"

SKILL_TOOL_NAMES = {"get_skill_instructions", "get_skill_reference", "get_skill_script"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_context():
    return RunContext(run_id="test-run", session_id="test-session")


def _make_session():
    return TeamSession(session_id="test-session")


def _make_run_response():
    return TeamRunOutput(run_id="test-run", session_id="test-session", team_id="test-team")


def _make_model():
    model = MagicMock()
    model.get_tools_for_api.return_value = []
    model.add_tool.return_value = None
    model.get_instructions_for_model = MagicMock(return_value=None)
    model.get_system_message_for_model = MagicMock(return_value=None)
    return model


def _make_skills():
    return Skills(loaders=[LocalSkills(SAMPLE_SKILLS_DIR)])


def _get_skill_tools(tools):
    return [t for t in tools if isinstance(t, Function) and t.name in SKILL_TOOL_NAMES]


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------


def test_skills_tools_registered_when_skills_set():
    """Skills tools are present in the tool list when team.skills is set."""
    team = Team(name="test-team", members=[], skills=_make_skills())

    tools = _determine_tools_for_model(
        team=team,
        model=_make_model(),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        team_run_context={},
        session=_make_session(),
        async_mode=False,
    )

    skill_tools = _get_skill_tools(tools)
    assert len(skill_tools) == 3
    tool_names = {t.name for t in skill_tools}
    assert tool_names == SKILL_TOOL_NAMES


def test_skills_tools_absent_when_skills_none():
    """No skills tools are present when team.skills is None."""
    team = Team(name="test-team", members=[])

    tools = _determine_tools_for_model(
        team=team,
        model=_make_model(),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        team_run_context={},
        session=_make_session(),
        async_mode=False,
    )

    skill_tools = _get_skill_tools(tools)
    assert len(skill_tools) == 0


# ---------------------------------------------------------------------------
# System message tests
# ---------------------------------------------------------------------------


def test_system_message_contains_skills_snippet():
    """System message includes the <skills_system> block when team.skills is set."""
    team = Team(name="test-team", mode="coordinate", members=[], skills=_make_skills())
    team.model = _make_model()
    session = TeamSession(session_id="test-session")

    msg = get_system_message(team, session)

    assert msg is not None
    assert "<skills_system>" in msg.content
    assert "get_skill_instructions" in msg.content


def test_system_message_omits_skills_when_none():
    """System message does not contain skills block when team.skills is None."""
    team = Team(name="test-team", mode="coordinate", members=[])
    team.model = _make_model()
    session = TeamSession(session_id="test-session")

    msg = get_system_message(team, session)

    if msg is not None:
        assert "<skills_system>" not in msg.content


# ---------------------------------------------------------------------------
# Deep copy tests
# ---------------------------------------------------------------------------


def test_deep_copy_shares_skills_by_reference():
    """deep_copy should share the Skills instance (heavy resource), not duplicate it."""
    skills = _make_skills()
    team = Team(name="test-team", members=[], skills=skills)
    copied = team.deep_copy()

    assert copied.skills is skills


async def test_asystem_message_contains_skills_snippet():
    """Async twin: system message includes the <skills_system> block when team.skills is set."""
    team = Team(name="test-team", mode="coordinate", members=[], skills=_make_skills())
    team.model = _make_model()

    msg = await aget_system_message(team, TeamSession(session_id="test-session"))

    assert msg is not None
    assert "<skills_system>" in msg.content
    assert "get_skill_instructions" in msg.content


# ---------------------------------------------------------------------------
# Persistence tests (save stores skill names; load re-resolves them from the db)
# ---------------------------------------------------------------------------


def _make_db(tmp_path):
    from agno.db.sqlite import SqliteDb

    return SqliteDb(db_file=str(tmp_path / "team-skills.db"))


def _create_skill_row(db, name: str = "release-notes"):
    db.create_skill(
        {
            "name": name,
            "description": f"Skill {name}",
            "instructions": f"Instructions for {name}.",
        }
    )


def test_to_dict_stores_skill_names_not_content(tmp_path):
    """A saved team carries only skill names; the content stays in the skills table."""
    db = _make_db(tmp_path)
    _create_skill_row(db)
    team = Team(name="test-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)]))

    config = team.to_dict()

    assert config["skills"] == {"names": ["release-notes"]}
    assert "Instructions for release-notes." not in json.dumps(config)


def test_save_then_load_round_trips_db_skills(tmp_path):
    """A saved then reloaded team keeps its db skills, resolved by name from the table."""
    db = _make_db(tmp_path)
    _create_skill_row(db)
    team = Team(name="test-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)]))
    team.save()

    loaded = get_team_by_id(db, team.id)

    assert loaded is not None and loaded.skills is not None
    assert "release-notes" in loaded.skills.get_system_prompt_snippet()
    instructions = json.loads(loaded.skills._get_skill_instructions("release-notes"))
    assert instructions["instructions"] == "Instructions for release-notes."

    # Twice: the second load must resolve from the table just as well as the first.
    reloaded = get_team_by_id(db, team.id)
    assert reloaded is not None and reloaded.skills is not None
    assert "release-notes" in reloaded.skills.get_system_prompt_snippet()


def test_from_dict_without_db_drops_skills_with_warning(tmp_path, monkeypatch):
    """With no db to resolve against, the reference is dropped with a warning, never an error."""
    db = _make_db(tmp_path)
    _create_skill_row(db)
    config = Team(name="test-team", members=[], skills=Skills(loaders=[DbSkills(db)])).to_dict()

    warnings: List[str] = []
    monkeypatch.setattr("agno.team._storage.log_warning", warnings.append)
    team = Team.from_dict(config)

    assert team.skills is None
    assert any("release-notes" in w for w in warnings)


def test_resave_during_outage_preserves_skill_names(tmp_path):
    """Data-loss regression, team twin: healthy save, load during an outage, resave, recover.

    The failed load leaves the mapping empty, but the loader still carries its
    configured names, so the resave must write them back instead of deleting them.
    """
    db = _make_db(tmp_path)
    _create_skill_row(db)
    team = Team(name="test-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)]))
    team.save()

    original = db.get_skills_with_content

    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    db.get_skills_with_content = boom
    loaded = get_team_by_id(db, team.id)
    assert loaded is not None and loaded.skills is not None
    assert loaded.skills.get_skill_names() == []
    loaded.save()
    db.get_skills_with_content = original

    assert db.get_config(component_id=team.id)["config"]["skills"] == {"names": ["release-notes"]}
    recovered = get_team_by_id(db, team.id)
    assert recovered is not None and recovered.skills is not None
    assert "release-notes" in recovered.skills.get_system_prompt_snippet()


def test_resave_of_fresh_instance_during_outage_preserves_names(tmp_path):
    """Data-loss regression, team twin: a redeploy during an outage must not erase saved names."""
    db = _make_db(tmp_path)
    _create_skill_row(db)
    Team(id="boot-team", name="boot-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)])).save()

    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    original = db.get_skills_with_content
    db.get_skills_with_content = boom
    fresh = Team(id="boot-team", name="boot-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)]))
    fresh.save()
    db.get_skills_with_content = original

    assert db.get_config(component_id="boot-team")["config"]["skills"] == {"names": ["release-notes"]}
    recovered = get_team_by_id(db, "boot-team")
    assert recovered is not None and recovered.skills is not None
    assert "release-notes" in recovered.skills.get_system_prompt_snippet()


def test_resave_during_partial_outage_merges_prior_names(tmp_path):
    """Partial-outage regression, team twin: one loader up, one down — the resave must
    union the surviving loader's names with the stored ones instead of dropping the
    down loader's.
    """
    from agno.db.sqlite import SqliteDb

    db = _make_db(tmp_path)
    _create_skill_row(db, "skill-a")
    _create_skill_row(db, "skill-b")
    # A second handle on the same file, so one backend can fail while the other serves.
    db2 = SqliteDb(db_file=str(tmp_path / "team-skills.db"))

    loaders = [DbSkills(db, names=["skill-a"]), DbSkills(db2)]
    Team(id="partial-team", name="partial-team", members=[], db=db, skills=Skills(loaders=loaders)).save()
    assert db.get_config(component_id="partial-team")["config"]["skills"] == {"names": ["skill-a", "skill-b"]}

    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    original = db2.get_skills_with_content
    db2.get_skills_with_content = boom
    fresh = Team(
        id="partial-team",
        name="partial-team",
        members=[],
        db=db,
        skills=Skills(loaders=[DbSkills(db, names=["skill-a"]), DbSkills(db2)]),
    )
    fresh.save()
    db2.get_skills_with_content = original

    assert db.get_config(component_id="partial-team")["config"]["skills"] == {"names": ["skill-a", "skill-b"]}
    recovered = get_team_by_id(db, "partial-team")
    assert recovered is not None and recovered.skills is not None
    snippet = recovered.skills.get_system_prompt_snippet()
    assert "skill-a" in snippet and "skill-b" in snippet


def test_deleted_skill_not_resurrected_when_loader_succeeded(tmp_path):
    """Team twin: a succeeded loader's reduced result is authoritative — a name deleted
    from the table is dropped on resave, not carried back from the prior config.
    """
    db = _make_db(tmp_path)
    _create_skill_row(db, "skill-a")
    _create_skill_row(db, "skill-b")
    Team(id="del-team", name="del-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)])).save()
    assert db.get_config(component_id="del-team")["config"]["skills"] == {"names": ["skill-a", "skill-b"]}

    db.delete_skill("skill-b")
    fresh = Team(id="del-team", name="del-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)]))
    fresh.save()

    assert db.get_config(component_id="del-team")["config"]["skills"] == {"names": ["skill-a"]}


def test_first_save_during_outage_omits_skills(tmp_path):
    """Team twin: with no prior config there is nothing to preserve; the first save omits the key."""
    db = _make_db(tmp_path)
    _create_skill_row(db)

    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    original = db.get_skills_with_content
    db.get_skills_with_content = boom
    team = Team(id="first-team", name="first-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)]))
    team.save()
    db.get_skills_with_content = original

    assert "skills" not in db.get_config(component_id="first-team")["config"]


def test_resave_after_successful_empty_load_omits_skills(tmp_path):
    """Team twin: a load that succeeded with zero rows is genuinely empty; the resave
    omits the key rather than resurrecting stale names.
    """
    db = _make_db(tmp_path)
    _create_skill_row(db)
    Team(id="empty-team", name="empty-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)])).save()
    db.delete_skill("release-notes")

    fresh = Team(id="empty-team", name="empty-team", members=[], db=db, skills=Skills(loaders=[DbSkills(db)]))
    fresh.save()

    assert "skills" not in db.get_config(component_id="empty-team")["config"]


def test_graph_hydrated_member_agent_resolves_skills(tmp_path):
    """Team.load's graph path hydrates member agents with their skills resolved.

    _hydrate_from_graph builds members from preloaded child graphs, bypassing
    get_agent_by_id, and those copies replace the members from_dict resolved —
    so the db has to reach that Agent.from_dict call too.
    """
    from agno.agent.agent import Agent
    from agno.team import _storage as team_storage

    db = _make_db(tmp_path)
    _create_skill_row(db)
    member = Agent(name="member-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    team = Team(name="graph-team", members=[member], db=db)
    team.save()

    graph = db.load_component_graph(team.id)
    loaded = team_storage._hydrate_from_graph(Team, graph, db=db)

    assert loaded is not None
    loaded_member = loaded.members[0]
    assert loaded_member.skills is not None
    assert "release-notes" in loaded_member.skills.get_system_prompt_snippet()


class _TeamSandboxExecutor(SkillExecutor):
    def run(self, script_path, *, args=None, timeout=30, cwd=None):
        raise AssertionError("the sandbox executor should not run on the host")


def test_team_from_dict_refuses_to_load_a_recorded_executor_that_is_missing(tmp_path):
    """The team twin: a sandbox policy must not silently become host execution."""
    from agno.db.sqlite import SqliteDb
    from agno.skills.errors import SkillError

    db = SqliteDb(db_file=str(tmp_path / "team_exec.db"))
    db.create_skill({"name": "greeter", "description": "d", "instructions": "i"})
    team = Team(
        name="t",
        id="t",
        members=[],
        db=db,
        skills=Skills(loaders=[DbSkills(db)], executor=_TeamSandboxExecutor()),
    )
    config = team.to_dict()
    assert config["skills"]["requires_executor"] is True

    with pytest.raises(SkillError, match="executor"):
        Team.from_dict(config, db=db)

    restored = Team.from_dict(config, db=db, skill_executor=_TeamSandboxExecutor())
    assert isinstance(restored.skills.executor, _TeamSandboxExecutor)


def test_team_with_the_default_executor_round_trips_unchanged(tmp_path):
    from agno.db.sqlite import SqliteDb
    from agno.skills.executor import LocalSkillExecutor

    db = SqliteDb(db_file=str(tmp_path / "team_default.db"))
    db.create_skill({"name": "greeter", "description": "d", "instructions": "i"})
    team = Team(name="t", id="t", members=[], db=db, skills=Skills(loaders=[DbSkills(db)]))

    config = team.to_dict()
    assert "requires_executor" not in config["skills"]
    assert type(Team.from_dict(config, db=db).skills.executor) is LocalSkillExecutor
