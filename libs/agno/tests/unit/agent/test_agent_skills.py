"""Tests for Skills integration on Agent.

Mirrors the team skills tests to verify parity:
- Skills tools are registered when agent.skills is set
- Skills tools are absent when agent.skills is None
- Skills system prompt snippet is injected into the system message
- Skills system prompt snippet is omitted when agent.skills is None
- deep_copy shares the Skills instance by reference (shared resource)
- save stores skill names; load re-resolves them from the database's skills table

The tool registration and prompt injection are hand-maintained sync/async twins on the Agent
(``_tools.get_tools``/``aget_tools``, ``_messages.get_system_message``/``aget_system_message``),
so both variants are asserted.
"""

import json
from typing import List
from unittest.mock import MagicMock

import pytest

from agno.agent._messages import aget_system_message, get_system_message
from agno.agent._tools import aget_tools, get_tools
from agno.agent.agent import Agent, get_agent_by_id
from agno.models.base import Function
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.session import AgentSession
from agno.skills import DbSkills, LocalSkills, Skills

SAMPLE_SKILLS_DIR = "cookbook/02_agents/16_skills/sample_skills"

SKILL_TOOL_NAMES = {"get_skill_instructions", "get_skill_reference", "get_skill_script"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_context():
    return RunContext(run_id="test-run", session_id="test-session")


def _make_session():
    return AgentSession(session_id="test-session")


def _make_run_response():
    return RunOutput(run_id="test-run", session_id="test-session", agent_id="test-agent")


def _make_model():
    model = MagicMock()
    model.get_tools_for_api.return_value = []
    model.add_tool.return_value = None
    model.get_instructions_for_model = MagicMock(return_value=None)
    model.get_system_message_for_model = MagicMock(return_value=None)
    return model


def _make_skills():
    return Skills(loaders=[LocalSkills(SAMPLE_SKILLS_DIR)])


def _make_agent(*, with_skills: bool) -> Agent:
    agent = Agent(name="test-agent", skills=_make_skills() if with_skills else None)
    agent.model = _make_model()
    return agent


def _get_skill_tools(tools):
    return [t for t in tools if isinstance(t, Function) and t.name in SKILL_TOOL_NAMES]


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------


def test_skills_tools_registered_when_skills_set():
    """Skills tools are present in the tool list when agent.skills is set."""
    tools = get_tools(
        agent=_make_agent(with_skills=True),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        session=_make_session(),
    )

    assert {t.name for t in _get_skill_tools(tools)} == SKILL_TOOL_NAMES


async def test_askills_tools_registered_when_skills_set():
    """Async twin: skills tools are present in the tool list when agent.skills is set."""
    tools = await aget_tools(
        agent=_make_agent(with_skills=True),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        session=_make_session(),
    )

    assert {t.name for t in _get_skill_tools(tools)} == SKILL_TOOL_NAMES


def test_skills_tools_absent_when_skills_none():
    """No skills tools are present when agent.skills is None."""
    tools = get_tools(
        agent=_make_agent(with_skills=False),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        session=_make_session(),
    )

    assert _get_skill_tools(tools) == []


# ---------------------------------------------------------------------------
# System message tests
# ---------------------------------------------------------------------------


def test_system_message_contains_skills_snippet():
    """System message includes the snippet verbatim when agent.skills is set."""
    agent = _make_agent(with_skills=True)

    msg = get_system_message(agent, _make_session())

    assert msg is not None
    assert agent.skills.get_system_prompt_snippet() in msg.content


async def test_asystem_message_contains_skills_snippet():
    """Async twin: system message includes the snippet verbatim when agent.skills is set."""
    agent = _make_agent(with_skills=True)

    msg = await aget_system_message(agent, _make_session())

    assert msg is not None
    assert agent.skills.get_system_prompt_snippet() in msg.content


def test_system_message_omits_skills_when_none():
    """System message does not contain skills block when agent.skills is None."""
    msg = get_system_message(_make_agent(with_skills=False), _make_session())

    if msg is not None:
        assert "<skills_system>" not in msg.content


# ---------------------------------------------------------------------------
# Deep copy tests
# ---------------------------------------------------------------------------


def test_deep_copy_shares_skills_by_reference():
    """deep_copy should share the Skills instance (heavy resource), not duplicate it."""
    skills = _make_skills()
    agent = Agent(name="test-agent", skills=skills)

    assert agent.deep_copy().skills is skills


# ---------------------------------------------------------------------------
# Persistence tests (save stores skill names; load re-resolves them from the db)
# ---------------------------------------------------------------------------


def _make_db(tmp_path):
    from agno.db.sqlite import SqliteDb

    return SqliteDb(db_file=str(tmp_path / "agent-skills.db"))


def _create_skill_row(db, name: str = "release-notes"):
    db.create_skill(
        {
            "name": name,
            "description": f"Skill {name}",
            "instructions": f"Instructions for {name}.",
            "scripts": {"draft.sh": "#!/bin/sh\necho draft\n"},
            "references": {"style.md": "Keep it short.\n"},
        }
    )


def test_to_dict_stores_skill_names_not_content(tmp_path):
    """A saved agent carries only skill names; the content stays in the skills table."""
    db = _make_db(tmp_path)
    _create_skill_row(db)
    agent = Agent(name="test-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))

    config = agent.to_dict()

    assert config["skills"] == {"names": ["release-notes"]}
    assert "Instructions for release-notes." not in json.dumps(config)


def test_save_then_load_round_trips_db_skills(tmp_path):
    """The #8979 fix, end to end: a saved then reloaded agent keeps its db skills,
    and the reloaded skills behave: snippet, instructions, reference, and script run.
    """
    db = _make_db(tmp_path)
    _create_skill_row(db)
    agent = Agent(name="test-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    agent.save()

    loaded = Agent.load(agent.id, db=db)

    assert loaded is not None and loaded.skills is not None
    assert "release-notes" in loaded.skills.get_system_prompt_snippet()
    instructions = json.loads(loaded.skills._get_skill_instructions("release-notes"))
    assert instructions["instructions"] == "Instructions for release-notes."
    reference = json.loads(loaded.skills._get_skill_reference("release-notes", "style.md"))
    assert reference["content"] == "Keep it short.\n"
    executed = json.loads(loaded.skills._get_skill_script("release-notes", "draft.sh", execute=True))
    assert executed["returncode"] == 0
    assert executed["stdout"].strip() == "draft"

    # Twice: the second load must resolve from the table just as well as the first.
    reloaded = Agent.load(agent.id, db=db)
    assert reloaded is not None and reloaded.skills is not None
    assert "release-notes" in reloaded.skills.get_system_prompt_snippet()


def test_loaded_agent_resolves_only_its_stored_names(tmp_path):
    """Resolution is by name: a loaded agent gets the names it stored, not the whole table."""
    db = _make_db(tmp_path)
    _create_skill_row(db, "release-notes")
    agent = Agent(name="test-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    agent.save()
    _create_skill_row(db, "unrelated-skill")

    loaded = Agent.load(agent.id, db=db)

    assert loaded is not None and loaded.skills is not None
    assert loaded.skills.get_skill_names() == ["release-notes"]


def test_load_with_missing_row_warns_and_loads_rest(tmp_path, monkeypatch):
    """A stored name with no row is skipped with a warning naming it; the rest still load."""
    db = _make_db(tmp_path)
    _create_skill_row(db, "release-notes")
    _create_skill_row(db, "doomed-skill")
    agent = Agent(name="test-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    agent.save()
    db.delete_skill("doomed-skill")

    warnings: List[str] = []
    monkeypatch.setattr("agno.skills.loaders.db.log_warning", warnings.append)
    loaded = Agent.load(agent.id, db=db)

    assert loaded is not None and loaded.skills is not None
    assert loaded.skills.get_skill_names() == ["release-notes"]
    assert any("doomed-skill" in w for w in warnings)


def test_from_dict_without_db_drops_skills_with_warning(tmp_path, monkeypatch):
    """With no db to resolve against, the reference is dropped with a warning, never an error."""
    db = _make_db(tmp_path)
    _create_skill_row(db)
    config = Agent(name="test-agent", skills=Skills(loaders=[DbSkills(db)])).to_dict()

    warnings: List[str] = []
    monkeypatch.setattr("agno.agent._storage.log_warning", warnings.append)
    agent = Agent.from_dict(config)

    assert agent.skills is None
    assert any("release-notes" in w for w in warnings)


def test_to_dict_with_no_loaded_skills_warns_and_omits_key(tmp_path, monkeypatch):
    """A failed or empty skills load is not persisted as an empty reference list.

    Persisting {"names": []} would silently erase the skills from the stored
    config — the #8979 silence this PR exists to remove — so to_dict warns and
    leaves the key out instead.
    """
    db = _make_db(tmp_path)
    _create_skill_row(db)

    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    original = db.get_skills_with_content
    db.get_skills_with_content = boom
    agent = Agent(name="test-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    db.get_skills_with_content = original

    warnings: List[str] = []
    monkeypatch.setattr("agno.agent._storage.log_warning", warnings.append)
    config = agent.to_dict()

    assert "skills" not in config
    assert any("will not be saved" in w for w in warnings)


def test_get_agent_by_id_resolves_skills(tmp_path):
    """The team-member load path resolves skills the same way a direct load does."""
    db = _make_db(tmp_path)
    _create_skill_row(db)
    agent = Agent(name="test-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    agent.save()

    loaded = get_agent_by_id(db, agent.id)

    assert loaded is not None and loaded.skills is not None
    assert "release-notes" in loaded.skills.get_system_prompt_snippet()


def test_resave_during_outage_preserves_skill_names(tmp_path):
    """Data-loss regression: healthy save, load during an outage, resave, recover.

    The failed load leaves the mapping empty, but the loader still carries its
    configured names, so the resave must write them back instead of deleting them.
    """
    db = _make_db(tmp_path)
    _create_skill_row(db)
    agent = Agent(name="test-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    agent.save()

    original = db.get_skills_with_content

    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    db.get_skills_with_content = boom
    loaded = Agent.load(agent.id, db=db)
    assert loaded is not None and loaded.skills is not None
    assert loaded.skills.get_skill_names() == []
    loaded.save()
    db.get_skills_with_content = original

    assert db.get_config(component_id=agent.id)["config"]["skills"] == {"names": ["release-notes"]}
    recovered = Agent.load(agent.id, db=db)
    assert recovered is not None and recovered.skills is not None
    assert "release-notes" in recovered.skills.get_system_prompt_snippet()


def test_resave_of_fresh_instance_during_outage_preserves_names(tmp_path):
    """Data-loss regression: a redeploy during an outage must not erase saved names.

    A fresh names=None instance has no configured names and a failed eager load, so
    serialization yields nothing; save() carries the stored names forward instead.
    """
    db = _make_db(tmp_path)
    _create_skill_row(db)
    Agent(id="boot-agent", name="boot-agent", db=db, skills=Skills(loaders=[DbSkills(db)])).save()

    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    original = db.get_skills_with_content
    db.get_skills_with_content = boom
    fresh = Agent(id="boot-agent", name="boot-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    fresh.save()
    db.get_skills_with_content = original

    assert db.get_config(component_id="boot-agent")["config"]["skills"] == {"names": ["release-notes"]}
    recovered = Agent.load("boot-agent", db=db)
    assert recovered is not None and recovered.skills is not None
    assert "release-notes" in recovered.skills.get_system_prompt_snippet()


def test_resave_during_partial_outage_merges_prior_names(tmp_path):
    """Partial-outage regression: one loader up, one down — the resave must union the
    surviving loader's names with the stored ones instead of dropping the down loader's.

    The down loader is names=None (nothing configured to reference), so only the
    prior stored config knows the names it contributed.
    """
    from agno.db.sqlite import SqliteDb

    db = _make_db(tmp_path)
    _create_skill_row(db, "skill-a")
    _create_skill_row(db, "skill-b")
    # A second handle on the same file, so one backend can fail while the other serves.
    db2 = SqliteDb(db_file=str(tmp_path / "agent-skills.db"))

    loaders = [DbSkills(db, names=["skill-a"]), DbSkills(db2)]
    Agent(id="partial-agent", name="partial-agent", db=db, skills=Skills(loaders=loaders)).save()
    assert db.get_config(component_id="partial-agent")["config"]["skills"] == {"names": ["skill-a", "skill-b"]}

    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    original = db2.get_skills_with_content
    db2.get_skills_with_content = boom
    fresh = Agent(
        id="partial-agent",
        name="partial-agent",
        db=db,
        skills=Skills(loaders=[DbSkills(db, names=["skill-a"]), DbSkills(db2)]),
    )
    fresh.save()
    db2.get_skills_with_content = original

    assert db.get_config(component_id="partial-agent")["config"]["skills"] == {"names": ["skill-a", "skill-b"]}
    recovered = Agent.load("partial-agent", db=db)
    assert recovered is not None and recovered.skills is not None
    snippet = recovered.skills.get_system_prompt_snippet()
    assert "skill-a" in snippet and "skill-b" in snippet


def test_deleted_skill_not_resurrected_when_loader_succeeded(tmp_path):
    """A succeeded loader's reduced result is authoritative: a name deleted from the
    table is dropped on resave, not carried back from the prior config.
    """
    db = _make_db(tmp_path)
    _create_skill_row(db, "skill-a")
    _create_skill_row(db, "skill-b")
    Agent(id="del-agent", name="del-agent", db=db, skills=Skills(loaders=[DbSkills(db)])).save()
    assert db.get_config(component_id="del-agent")["config"]["skills"] == {"names": ["skill-a", "skill-b"]}

    db.delete_skill("skill-b")
    fresh = Agent(id="del-agent", name="del-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    fresh.save()

    assert db.get_config(component_id="del-agent")["config"]["skills"] == {"names": ["skill-a"]}


def test_first_save_during_outage_omits_skills(tmp_path):
    """With no prior config there is nothing to preserve: the first save omits the key."""
    db = _make_db(tmp_path)
    _create_skill_row(db)

    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    original = db.get_skills_with_content
    db.get_skills_with_content = boom
    agent = Agent(id="first-agent", name="first-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    agent.save()
    db.get_skills_with_content = original

    assert "skills" not in db.get_config(component_id="first-agent")["config"]


def test_resave_after_successful_empty_load_omits_skills(tmp_path):
    """A load that succeeded with zero rows is genuinely empty: the resave omits the
    key rather than resurrecting stale names.
    """
    db = _make_db(tmp_path)
    _create_skill_row(db)
    Agent(id="empty-agent", name="empty-agent", db=db, skills=Skills(loaders=[DbSkills(db)])).save()
    db.delete_skill("release-notes")

    fresh = Agent(id="empty-agent", name="empty-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    fresh.save()

    assert "skills" not in db.get_config(component_id="empty-agent")["config"]


def test_to_dict_with_empty_skills_warns_and_omits_key(monkeypatch):
    """A genuinely empty Skills — nothing configured, nothing loaded — is not persisted."""
    agent = Agent(name="test-agent", skills=Skills(loaders=[]))

    warnings: List[str] = []
    monkeypatch.setattr("agno.agent._storage.log_warning", warnings.append)
    config = agent.to_dict()

    assert "skills" not in config
    assert any("will not be saved" in w for w in warnings)


def test_studio_load_resolves_skills(tmp_path):
    """The Studio loader bypasses Agent.load, so it must pass db to from_dict itself."""
    from agno.registry.registry import Registry
    from agno.tools.studio import StudioTools

    db = _make_db(tmp_path)
    _create_skill_row(db)
    agent = Agent(name="studio-agent", db=db, skills=Skills(loaders=[DbSkills(db)]))
    agent.save()

    loaded = StudioTools(registry=Registry(), db=db)._load_agent_from_db(agent.id)

    assert loaded is not None and loaded.skills is not None
    assert "release-notes" in loaded.skills.get_system_prompt_snippet()


def test_from_dict_positional_second_arg_is_registry(tmp_path):
    """The pre-existing positional contract holds: from_dict(config, registry) binds
    the registry, and db is keyword-only, so it cannot silently take registry's slot.
    """
    from agno.registry.registry import Registry

    db = _make_db(tmp_path)
    _create_skill_row(db)
    config = Agent(name="test-agent", db=db, skills=Skills(loaders=[DbSkills(db)])).to_dict()

    agent = Agent.from_dict(config, Registry())
    # No db was bound, so the skills reference is dropped — not resolved against the registry.
    assert agent.skills is None

    with pytest.raises(TypeError):
        Agent.from_dict(config, Registry(), db)


async def test_asystem_message_refreshes_skills_through_async_db(tmp_path):
    """The async message path reads an async backend through its awaited skills method.

    AsyncSqliteDb has no sync skills read at all, so the snippet appearing in the
    system message proves the refresh went through the awaited async method.
    """
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    db = AsyncSqliteDb(db_file=str(tmp_path / "agent-skills-async.db"))
    await db.create_skill({"name": "async-skill", "description": "d", "instructions": "i"})

    agent = Agent(name="test-agent", skills=Skills(loaders=[DbSkills(db)]))
    agent.model = _make_model()
    msg = await aget_system_message(agent, _make_session())

    assert msg is not None
    assert "async-skill" in msg.content
