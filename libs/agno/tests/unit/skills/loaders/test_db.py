"""Unit tests for the DbSkills loader."""

import json
import os
import subprocess
import sys
import tempfile
from typing import List

import pytest

from agno.skills.agent_skills import Skills
from agno.skills.errors import SkillError, SkillValidationError
from agno.skills.loaders.base import SkillLoader
from agno.skills.loaders.db import DbSkills
from agno.skills.loaders.local import LocalSkills

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sqlite_db():
    from agno.db.sqlite.sqlite import SqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SqliteDb(db_file=path)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def async_sqlite_db():
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = AsyncSqliteDb(db_file=path)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def skill_data():
    return {
        "name": "release-notes",
        "description": "Draft release notes",
        "instructions": "Read the diff, then draft notes.",
        "scripts": {"draft.sh": "#!/bin/sh\necho draft\n"},
        "references": {"style.md": "Keep it short.\n"},
        "metadata": {"version": "1.0"},
        "license": "MIT",
        "compatibility": "python>=3.8",
        "allowed_tools": ["bash"],
    }


# ============================================================================
# LOADER SHAPE TESTS
# ============================================================================


def test_db_skills_is_a_skill_loader(sqlite_db) -> None:
    """Test that DbSkills implements SkillLoader and is the one refresh-per-request loader."""
    loader = DbSkills(sqlite_db)
    assert isinstance(loader, SkillLoader)
    assert DbSkills.refresh_per_request is True
    assert SkillLoader.refresh_per_request is False
    assert LocalSkills.refresh_per_request is False


def test_load_builds_content_carrying_skills_from_rows(sqlite_db, skill_data) -> None:
    """Test that load() turns stored rows into content-carrying Skills equivalent to them."""
    sqlite_db.create_skill(skill_data)
    sqlite_db.create_skill({"name": "no-files", "description": "d", "instructions": "i"})

    skills = DbSkills(sqlite_db).load()

    assert [s.name for s in skills] == ["no-files", "release-notes"]
    loaded = skills[1]
    assert loaded.source_path is None
    assert loaded.description == skill_data["description"]
    assert loaded.instructions == skill_data["instructions"]
    assert loaded.scripts == ["draft.sh"]
    assert loaded.references == ["style.md"]
    assert loaded.script_contents == skill_data["scripts"]
    assert loaded.reference_contents == skill_data["references"]
    assert loaded.metadata == skill_data["metadata"]
    assert loaded.allowed_tools == skill_data["allowed_tools"]


def test_load_empty_db_returns_no_skills(sqlite_db) -> None:
    """Test that a database with no skills table yet loads zero skills, not an error."""
    assert DbSkills(sqlite_db).load() == []


def test_load_names_subset_in_one_batched_query(sqlite_db, skill_data) -> None:
    """Test that a names subset loads just those rows, through one batched read."""
    for name in ("alpha", "beta", "gamma"):
        sqlite_db.create_skill({**skill_data, "name": name})

    calls: List[dict] = []
    original = sqlite_db.get_skills_with_content

    def counting(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    sqlite_db.get_skills_with_content = counting

    skills = DbSkills(sqlite_db, names=["gamma", "alpha"]).load()

    assert [s.name for s in skills] == ["alpha", "gamma"]
    # One batched read, carrying the owner scope: no user means shared skills only.
    assert calls == [{"names": ["gamma", "alpha"], "user_id": None, "include_shared": True}]


def test_load_missing_name_warns_and_loads_rest(sqlite_db, skill_data, monkeypatch) -> None:
    """Test that a requested name with no row is skipped with a warning naming it."""
    sqlite_db.create_skill(skill_data)

    warnings: List[str] = []
    monkeypatch.setattr("agno.skills.loaders.db.log_warning", warnings.append)

    skills = DbSkills(sqlite_db, names=["release-notes", "missing-skill"]).load()

    assert [s.name for s in skills] == ["release-notes"]
    assert len(warnings) == 1
    assert "missing-skill" in warnings[0]


def test_validate_rejects_invalid_stored_name(sqlite_db, skill_data) -> None:
    """Test that validation catches a stored skill the write path did not spec-check."""
    # create_skill validates content shape, not name format, so this row can exist.
    sqlite_db.create_skill({**skill_data, "name": "Invalid_Name"})

    with pytest.raises(SkillValidationError, match="Invalid_Name"):
        DbSkills(sqlite_db).load()

    skills = DbSkills(sqlite_db, validate=False).load()
    assert [s.name for s in skills] == ["Invalid_Name"]


# ============================================================================
# SERVING FROM THE TABLE ONLY (spec 3.3: no skill directory on disk)
# ============================================================================


def test_skills_served_from_db_rows_only(sqlite_db, skill_data) -> None:
    """Test that instructions, references and script execution all work from table rows alone."""
    sqlite_db.create_skill(skill_data)
    skills = Skills(loaders=[DbSkills(sqlite_db)])

    assert "release-notes" in skills.get_system_prompt_snippet()

    instructions = json.loads(skills._get_skill_instructions("release-notes"))
    assert instructions["instructions"] == skill_data["instructions"]

    reference = json.loads(skills._get_skill_reference("release-notes", "style.md"))
    assert reference["content"] == "Keep it short.\n"

    executed = json.loads(skills._get_skill_script("release-notes", "draft.sh", execute=True))
    assert "error" not in executed
    assert executed["returncode"] == 0
    assert executed["stdout"].strip() == "draft"


def test_db_row_edit_shows_up_in_next_snippet(sqlite_db, skill_data) -> None:
    """Test that editing a row between two requests updates the second snippet, with no reload()."""
    sqlite_db.create_skill(skill_data)
    skills = Skills(loaders=[DbSkills(sqlite_db)])

    assert "Draft release notes" in skills.get_system_prompt_snippet()
    sqlite_db.update_skill("release-notes", 1, description="Now refreshed from the table")
    assert "Now refreshed from the table" in skills.get_system_prompt_snippet()


def test_db_outage_keeps_last_loaded_skills(sqlite_db, skill_data, monkeypatch) -> None:
    """Test the whole chain: a failing database read leaves the last loaded skills serving.

    Depends on get_skills_with_content raising on failure rather than returning [] the
    way the sibling reads do; if it swallowed, this snippet would come back empty.
    """
    sqlite_db.create_skill(skill_data)
    skills = Skills(loaders=[DbSkills(sqlite_db)])
    assert "release-notes" in skills.get_system_prompt_snippet()

    def boom():
        raise RuntimeError("database down")

    monkeypatch.setattr(sqlite_db, "Session", boom)
    # Twice: the second request during the outage must also serve the cached mapping.
    assert "release-notes" in skills.get_system_prompt_snippet()
    assert "release-notes" in skills.get_system_prompt_snippet()


def test_refresh_during_postgres_outage_keeps_last_loaded_skills(sqlite_db, skill_data) -> None:
    """The live-test regression, end to end: the refresh fails against a REAL unreachable
    Postgres — the outage the patched-Session tests could not reproduce, because there the
    failure fires inside _get_table and used to read as an empty table — and the last
    loaded skills survive it.
    """
    pytest.importorskip("psycopg")
    from sqlalchemy import create_engine

    from agno.db.postgres import PostgresDb

    sqlite_db.create_skill(skill_data)
    loader = DbSkills(sqlite_db)
    skills = Skills(loaders=[loader])
    assert "release-notes" in skills.get_system_prompt_snippet()

    dead_engine = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:9/dead",
        connect_args={"connect_timeout": 2},
    )
    loader.db = PostgresDb(db_engine=dead_engine, db_schema="ai")
    # Twice: the second request during the outage must also serve the cached mapping.
    assert "release-notes" in skills.get_system_prompt_snippet()
    assert "release-notes" in skills.get_system_prompt_snippet()


# ============================================================================
# ASYNC LOADING (spec 3.5 carry-forward: the async message path awaits the read)
# ============================================================================


async def test_aload_awaits_an_async_database(async_sqlite_db, skill_data) -> None:
    """Test that aload reads an async backend through its awaited skills method."""
    await async_sqlite_db.create_skill(skill_data)

    skills = await DbSkills(async_sqlite_db).aload()

    assert [s.name for s in skills] == ["release-notes"]
    assert skills[0].instructions == skill_data["instructions"]
    assert skills[0].script_contents == skill_data["scripts"]


async def test_aload_with_sync_database_matches_load(sqlite_db, skill_data) -> None:
    """Test that aload on a sync backend returns the same skills as load."""
    sqlite_db.create_skill(skill_data)
    loader = DbSkills(sqlite_db)

    assert [s.name for s in await loader.aload()] == [s.name for s in loader.load()]


def test_load_rejects_an_async_database(async_sqlite_db) -> None:
    """Test that the sync load names the problem instead of iterating a coroutine."""
    with pytest.raises(SkillError, match="aload"):
        DbSkills(async_sqlite_db).load()


async def test_async_db_skills_start_empty_then_refresh(async_sqlite_db, skill_data) -> None:
    """Test the async-backed lifecycle: the eager constructor load cannot await, so the
    mapping starts empty; the first async refresh pulls the rows; an edit shows on the next.
    """
    await async_sqlite_db.create_skill(skill_data)
    skills = Skills(loaders=[DbSkills(async_sqlite_db)])
    assert skills.get_all_skills() == []

    assert "release-notes" in await skills.aget_system_prompt_snippet()

    await async_sqlite_db.update_skill("release-notes", 1, description="Refreshed from the async table")
    assert "Refreshed from the async table" in await skills.aget_system_prompt_snippet()


# ============================================================================
# IMPORT CYCLE
# ============================================================================


def test_no_import_cycle_between_db_schemas_and_loader() -> None:
    """Test both import orders in fresh interpreters.

    agno.db.schemas.skills imports agno.skills, whose loaders package imports this
    loader. A module-level SkillRow import in the loader would find
    agno.db.schemas.skills partially initialized and fail; the point-of-use import
    breaks the cycle. Guard both directions.
    """
    for imports in (
        "import agno.db.schemas.skills; from agno.skills import DbSkills",
        "from agno.skills import DbSkills; import agno.db.schemas.skills",
    ):
        result = subprocess.run(
            [sys.executable, "-c", f"{imports}; print('ok')"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ok"


# ============================================================================
# OWNER SCOPING
# ============================================================================


def _seed_owned_skills(db) -> None:
    """One skill per owner plus a shared one, so a scoped read has something to exclude."""
    db.create_skill(
        {
            "name": "alice-private",
            "description": "Alice's",
            "instructions": "i",
            "user_id": "alice",
            "scripts": {"secret.py": "print('ALICE SECRET')"},
        }
    )
    db.create_skill({"name": "bob-private", "description": "Bob's", "instructions": "i", "user_id": "bob"})
    db.create_skill({"name": "shared-skill", "description": "Everyone's", "instructions": "i"})


def test_load_scoped_to_a_user_returns_own_plus_shared(sqlite_db) -> None:
    """A run's skills are the caller's own plus the shared ones -- never another owner's.

    Skills carry executable scripts, so loading across owners hands one tenant another
    tenant's instructions and code.
    """
    _seed_owned_skills(sqlite_db)

    skills = DbSkills(sqlite_db).load(user_id="alice")

    assert sorted(s.name for s in skills) == ["alice-private", "shared-skill"]
    assert all("ALICE SECRET" not in str(s.script_contents) for s in skills if s.name != "alice-private")


def test_load_without_a_user_returns_only_shared_skills(sqlite_db) -> None:
    """No user context means no owner to match, so only shared skills are visible."""
    _seed_owned_skills(sqlite_db)

    skills = DbSkills(sqlite_db).load()

    assert sorted(s.name for s in skills) == ["shared-skill"]


def test_eager_constructor_load_cannot_surface_owned_skills(sqlite_db) -> None:
    """The eager load in Skills.__init__ runs before any run exists, so it has no user.

    It must not fall back to reading every owner's rows: an agent built at import time
    would hold every tenant's skills in memory before serving a single request.
    """
    _seed_owned_skills(sqlite_db)

    skills = Skills(loaders=[DbSkills(sqlite_db)])

    assert sorted(skills._skills) == ["shared-skill"]


def test_refresh_scopes_to_the_run_user(sqlite_db) -> None:
    """The per-request refresh carries the run's user, so the snippet is that user's view."""
    _seed_owned_skills(sqlite_db)
    skills = Skills(loaders=[DbSkills(sqlite_db)])

    snippet = skills.get_system_prompt_snippet(user_id="bob")

    assert "bob-private" in snippet
    assert "shared-skill" in snippet
    assert "alice-private" not in snippet


@pytest.mark.asyncio
async def test_async_load_scoped_to_a_user(async_sqlite_db) -> None:
    await async_sqlite_db.create_skill(
        {"name": "alice-private", "description": "A", "instructions": "i", "user_id": "alice"}
    )
    await async_sqlite_db.create_skill({"name": "shared-skill", "description": "S", "instructions": "i"})

    skills = Skills(loaders=[DbSkills(async_sqlite_db)])
    snippet = await skills.aget_system_prompt_snippet(user_id="alice")

    assert "alice-private" in snippet and "shared-skill" in snippet

    other = await skills.aget_system_prompt_snippet(user_id="bob")
    assert "alice-private" not in other


def test_a_loader_without_owner_scoping_is_called_untouched(tmp_path, sqlite_db) -> None:
    """A loader whose source has no owners keeps its original signature.

    Only loaders declaring owner_scoped receive the run's user, so a loader written
    before owner scoping existed -- LocalSkills, or any third-party one -- is still
    called with no arguments and cannot break on an unexpected keyword.
    """
    folder = tmp_path / "greeter"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: greeter\ndescription: says hi\n---\n\nSay hello.\n", encoding="utf-8")
    local = LocalSkills(str(tmp_path))
    assert local.owner_scoped is False
    assert DbSkills(sqlite_db).owner_scoped is True

    # A refresh carrying a user must not pass it to the un-scoped loader.
    skills = Skills(loaders=[local])
    assert "greeter" in skills.get_system_prompt_snippet(user_id="alice")


# ============================================================================
# WHAT A SAVE PERSISTS
# ============================================================================


def _local_skill_folder(tmp_path, name="greeter"):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: says hi\n---\n\nSay hello.\n", encoding="utf-8")
    return tmp_path


def test_only_database_backed_skills_are_persisted(tmp_path, sqlite_db, monkeypatch) -> None:
    """A saved reference is resolved against the skills table on load, so only skills that
    actually live there may be saved.

    Persisting a filesystem skill's name would resolve it to whatever DB row happens to
    share that name, or to nothing at all -- silently swapping the skill either way.
    """
    sqlite_db.create_skill({"name": "db-skill", "description": "d", "instructions": "i"})
    skills = Skills(loaders=[LocalSkills(str(_local_skill_folder(tmp_path))), DbSkills(sqlite_db)])
    assert sorted(skills._skills) == ["db-skill", "greeter"]

    warnings: List[str] = []
    monkeypatch.setattr("agno.skills.agent_skills.log_warning", warnings.append)

    assert skills.get_persistable_skill_names() == ["db-skill"]
    assert len(warnings) == 1
    assert "greeter" in warnings[0]


def test_database_backed_skills_still_round_trip(sqlite_db) -> None:
    """The real case must be untouched: DB skills are still saved by name."""
    sqlite_db.create_skill({"name": "alpha", "description": "d", "instructions": "i"})
    sqlite_db.create_skill({"name": "beta", "description": "d", "instructions": "i"})

    skills = Skills(loaders=[DbSkills(sqlite_db)])

    assert sorted(skills.get_persistable_skill_names()) == ["alpha", "beta"]


def test_a_failed_database_load_still_persists_its_configured_names(sqlite_db, monkeypatch) -> None:
    """The outage guard stays: a loader that never loaded still says what to resolve."""

    def boom():
        raise RuntimeError("database down")

    skills = Skills(loaders=[DbSkills(sqlite_db, names=["alpha", "beta"])])
    monkeypatch.setattr(sqlite_db, "Session", boom)
    skills._refresh_loaders()

    assert sorted(skills.get_persistable_skill_names()) == ["alpha", "beta"]


def test_a_local_only_agent_persists_nothing(tmp_path, monkeypatch) -> None:
    """With no database loader there is nothing resolvable, so nothing is saved."""
    skills = Skills(loaders=[LocalSkills(str(_local_skill_folder(tmp_path)))])

    warnings: List[str] = []
    monkeypatch.setattr("agno.skills.agent_skills.log_warning", warnings.append)

    assert skills.get_persistable_skill_names() == []
    assert any("greeter" in w for w in warnings)
