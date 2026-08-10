import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.schemas.skills import SkillRow
from agno.db.sqlite.schemas import SKILLS_TABLE_SCHEMA
from agno.skills.errors import SkillError
from agno.skills.loaders.db import skill_from_row
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


@pytest.fixture
def skill_folder(tmp_path):
    """A real skill folder on disk, loadable by LocalSkills."""
    folder = tmp_path / "release-notes"
    (folder / "scripts").mkdir(parents=True)
    (folder / "references").mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: release-notes\ndescription: Draft release notes\n---\nRead the diff, then draft notes.",
        encoding="utf-8",
    )
    (folder / "scripts" / "draft.sh").write_text("#!/bin/sh\necho draft\n", encoding="utf-8")
    (folder / "references" / "style.md").write_text("Keep it short.\n", encoding="utf-8")
    return folder


def _row_dict_from_path_backed_skill(skill, **overrides):
    """Publish a path-backed skill: read its declared files and shape them as a row.

    The library has no helper for this - a caller publishing a local skill reads the
    files itself - so the tests that need a stored copy of a real on-disk skill do the
    same here.
    """
    root = Path(skill.source_path)
    row = {
        "id": str(uuid4()),
        "name": skill.name,
        "description": skill.description,
        "instructions": skill.instructions,
        "source_type": skill.source_type,
        "scripts": {f: (root / "scripts" / f).read_text(encoding="utf-8") for f in skill.scripts},
        "references": {f: (root / "references" / f).read_text(encoding="utf-8") for f in skill.references},
    }
    row.update(overrides)
    return row


# ============================================================================
# SKILLS_TABLE_SCHEMA TESTS
# ============================================================================


def test_schema_registered_on_both_backends():
    from agno.db.postgres.schemas import get_table_schema_definition as pg_schema
    from agno.db.sqlite.schemas import get_table_schema_definition as sqlite_schema

    pg = pg_schema("skills")
    sq = sqlite_schema("skills")
    assert list(pg.keys()) == list(sq.keys())


def test_schema_has_required_columns():
    expected = {
        "id",
        "name",
        "user_id",
        "description",
        "source_type",
        "instructions",
        "scripts",
        "references",
        "metadata",
        "license",
        "compatibility",
        "allowed_tools",
        "version",
        "created_at",
        "updated_at",
    }
    assert set(SKILLS_TABLE_SCHEMA.keys()) == expected


def test_name_is_unique_and_indexed():
    assert SKILLS_TABLE_SCHEMA["name"]["unique"] is True
    assert SKILLS_TABLE_SCHEMA["name"]["index"] is True
    assert SKILLS_TABLE_SCHEMA["name"]["nullable"] is False


def test_user_id_is_nullable_indexed_and_not_part_of_any_key():
    # Meaning 1: user_id is ownership metadata. Name alone stays the unique key.
    from agno.db.postgres.schemas import SKILLS_TABLE_SCHEMA as PG_SCHEMA

    for schema in (SKILLS_TABLE_SCHEMA, PG_SCHEMA):
        assert schema["user_id"]["nullable"] is True
        assert schema["user_id"]["index"] is True
        assert "unique" not in schema["user_id"]
        assert "_unique_constraints" not in schema
        assert "_partial_unique_indexes" not in schema


def test_version_defaults_to_one():
    assert SKILLS_TABLE_SCHEMA["version"]["default"] == 1
    assert SKILLS_TABLE_SCHEMA["version"]["nullable"] is False


def test_content_columns_not_nullable():
    assert SKILLS_TABLE_SCHEMA["scripts"]["nullable"] is False
    assert SKILLS_TABLE_SCHEMA["references"]["nullable"] is False
    assert SKILLS_TABLE_SCHEMA["instructions"]["nullable"] is False


def test_table_name_plumbing():
    from agno.db.postgres import PostgresDb
    from agno.db.postgres.async_postgres import AsyncPostgresDb

    mock_engine = MagicMock()
    mock_engine.url = "postgresql://test@localhost/test"
    db = PostgresDb(db_engine=mock_engine)
    assert db.skills_table_name == "agno_skills"
    assert db.to_dict()["skills_table"] == "agno_skills"

    custom = PostgresDb(db_engine=mock_engine, skills_table="my_skills")
    assert custom.skills_table_name == "my_skills"

    async_engine = Mock(spec=AsyncEngine)
    async_engine.url = "fake:///url"
    adb = AsyncPostgresDb(db_engine=async_engine, skills_table="my_skills")
    assert adb.skills_table_name == "my_skills"


def test_backend_without_skills_support_raises_not_implemented():
    from agno.db.in_memory import InMemoryDb

    db = InMemoryDb()
    with pytest.raises(NotImplementedError):
        db.create_skill({"name": "x"})
    with pytest.raises(NotImplementedError):
        db.get_skill("x")
    with pytest.raises(NotImplementedError):
        db.get_skills()
    with pytest.raises(NotImplementedError):
        db.get_skills_with_content()
    with pytest.raises(NotImplementedError):
        db.update_skill("x", 1)
    with pytest.raises(NotImplementedError):
        db.delete_skill("x")


# ============================================================================
# SKILLROW MODEL TESTS
# ============================================================================


def test_skill_row_dict_roundtrip(skill_data):
    row = SkillRow.from_dict({**skill_data, "id": "abc"})
    restored = SkillRow.from_dict(row.to_dict())
    assert restored == row


def test_skill_row_from_dict_ignores_unknown_keys(skill_data):
    row = SkillRow.from_dict({**skill_data, "id": "abc", "not_a_column": True})
    assert not hasattr(row, "not_a_column")


def test_skill_from_row_passes_empty_dicts_through_verbatim():
    # {} is a valid content-carrying shape (a skill with no files). Collapsing it to
    # None would make the Skill look path-backed-without-a-path and fail validation.
    row = SkillRow(id="abc", name="minimal", description="d", instructions="i")
    skill = skill_from_row(row)
    assert skill.source_path is None
    assert skill.script_contents == {}
    assert skill.reference_contents == {}
    assert skill.scripts == []
    assert skill.references == []


def test_skill_from_row_carries_content(skill_data):
    row = SkillRow.from_dict({**skill_data, "id": "abc"})
    skill = skill_from_row(row)
    assert skill.source_path is None
    assert skill.scripts == ["draft.sh"]
    assert skill.references == ["style.md"]
    assert skill.script_contents == {"draft.sh": "#!/bin/sh\necho draft\n"}
    assert skill.reference_contents == {"style.md": "Keep it short.\n"}
    assert skill.metadata == {"version": "1.0"}
    assert skill.allowed_tools == ["bash"]


def test_path_backed_skill_round_trips_through_a_row(skill_folder):
    """A path-backed skill's declared files survive a trip through the row shape.

    Previously covered via SkillRow.from_skill, which had no production caller and was
    removed; the publish step is done here the way a caller would do it.
    """
    skills = LocalSkills(str(skill_folder)).load()
    assert len(skills) == 1
    loaded = skills[0]
    assert loaded.source_path is not None

    row = SkillRow.from_dict(_row_dict_from_path_backed_skill(loaded))
    assert row.scripts == {"draft.sh": "#!/bin/sh\necho draft\n"}
    assert row.references == {"style.md": "Keep it short.\n"}

    back = skill_from_row(row)
    assert back.source_path is None
    assert back.name == loaded.name
    assert back.description == loaded.description
    assert back.instructions == loaded.instructions
    assert back.scripts == loaded.scripts
    assert back.references == loaded.references


# ============================================================================
# SYNC SQLITE CRUD TESTS
# ============================================================================


def test_create_skill_sets_version_one_and_persists(sqlite_db, skill_data):
    created = sqlite_db.create_skill(skill_data)
    assert created["version"] == 1
    assert created["id"]
    assert created["created_at"]

    stored = sqlite_db.get_skill("release-notes")
    assert stored is not None
    assert stored["instructions"] == skill_data["instructions"]
    assert stored["scripts"] == skill_data["scripts"]
    assert stored["references"] == skill_data["references"]


def test_create_skill_duplicate_name_raises_skill_error(sqlite_db, skill_data):
    sqlite_db.create_skill(skill_data)
    with pytest.raises(SkillError, match="release-notes"):
        sqlite_db.create_skill({"name": "release-notes", "description": "other", "instructions": "other"})
    # The original row is untouched
    assert sqlite_db.get_skill("release-notes")["description"] == skill_data["description"]


def test_create_skill_rejects_malformed_content_before_writing(sqlite_db, skill_data):
    # A non-dict scripts value fails in the content check (.items() on None); a missing
    # required field would fail earlier as TypeError in SkillRow.__init__.
    with pytest.raises(AttributeError):
        sqlite_db.create_skill({**skill_data, "scripts": None})
    _, total = sqlite_db.get_skills()
    assert total == 0


def test_create_skill_rejects_non_string_script_value(sqlite_db, skill_data):
    # Skill's own validation is structural; the row model rejects non-string
    # content before the write, or it would only fail later at materialization.
    with pytest.raises(SkillError, match="run.sh"):
        sqlite_db.create_skill({**skill_data, "scripts": {"run.sh": 123}})
    _, total = sqlite_db.get_skills()
    assert total == 0


def test_create_skill_rejects_non_string_reference_content(sqlite_db, skill_data):
    with pytest.raises(SkillError, match="notes.md"):
        sqlite_db.create_skill({**skill_data, "references": {"notes.md": 42}})
    # a non-string filename key is rejected the same way
    with pytest.raises(SkillError):
        sqlite_db.create_skill({**skill_data, "references": {123: "text"}})
    _, total = sqlite_db.get_skills()
    assert total == 0


def test_update_skill_rejects_non_string_content(sqlite_db, skill_data):
    sqlite_db.create_skill(skill_data)
    with pytest.raises(SkillError, match="bad.sh"):
        sqlite_db.update_skill("release-notes", 1, scripts={"bad.sh": 1})
    stored = sqlite_db.get_skill("release-notes")
    assert stored["version"] == 1
    assert stored["scripts"] == skill_data["scripts"]


def test_content_type_validation_allows_valid_shapes(sqlite_db, skill_data):
    # Guard against over-broad validation: str content and empty dicts still pass
    sqlite_db.create_skill(skill_data)
    sqlite_db.create_skill({"name": "no-files", "description": "d", "instructions": "i"})
    updated = sqlite_db.update_skill("release-notes", 1, scripts={"draft.sh": "echo ok"})
    assert updated["version"] == 2
    _, total = sqlite_db.get_skills()
    assert total == 2


def test_stored_row_reads_back_as_content_carrying_skill(sqlite_db, skill_folder):
    # The publish path: a real LocalSkills-loaded (path-backed) skill, written to the
    # table, reads back through skill_from_row() as an equivalent content-carrying Skill.
    loaded = LocalSkills(str(skill_folder)).load()[0]
    sqlite_db.create_skill(_row_dict_from_path_backed_skill(loaded))

    stored = sqlite_db.get_skill("release-notes")
    skill = skill_from_row(SkillRow.from_dict(stored))
    assert skill.source_path is None
    assert skill.name == loaded.name
    assert skill.instructions == loaded.instructions
    assert skill.scripts == loaded.scripts
    assert skill.references == loaded.references
    assert skill.script_contents == {"draft.sh": "#!/bin/sh\necho draft\n"}
    assert skill.reference_contents == {"style.md": "Keep it short.\n"}


def test_get_skills_returns_metadata_only(sqlite_db, skill_data):
    sqlite_db.create_skill(skill_data)
    rows, total = sqlite_db.get_skills()
    assert total == 1
    assert len(rows) == 1
    row = rows[0]
    assert "instructions" not in row
    assert "scripts" not in row
    assert "references" not in row
    assert row["name"] == "release-notes"
    assert row["version"] == 1
    assert row["metadata"] == {"version": "1.0"}


def test_get_skills_projection_covers_all_metadata_columns(sqlite_db, skill_data):
    # Guards the hand-maintained projection in get_skills: a column added to the
    # table schema must be added to the select (or named heavy) or this fails.
    sqlite_db.create_skill(skill_data)
    rows, _ = sqlite_db.get_skills()
    expected = set(SKILLS_TABLE_SCHEMA.keys()) - {"instructions", "scripts", "references"}
    assert set(rows[0].keys()) == expected


def test_get_skills_paginates(sqlite_db, skill_data):
    for n in range(3):
        sqlite_db.create_skill({**skill_data, "name": f"skill-{n}"})
    rows, total = sqlite_db.get_skills(limit=2, page=2)
    assert total == 3
    assert len(rows) == 1


def test_get_skill_missing_returns_none(sqlite_db):
    assert sqlite_db.get_skill("missing") is None


def test_update_skill_checks_and_bumps_version(sqlite_db, skill_data):
    sqlite_db.create_skill(skill_data)

    updated = sqlite_db.update_skill("release-notes", 1, description="updated")
    assert updated is not None
    assert updated["description"] == "updated"
    assert updated["version"] == 2

    # Run the guard twice: the same expected_version must not apply a second time
    stale = sqlite_db.update_skill("release-notes", 1, description="stale write")
    assert stale is None
    assert sqlite_db.get_skill("release-notes")["description"] == "updated"

    again = sqlite_db.update_skill("release-notes", 2, description="third")
    assert again["version"] == 3


def test_update_skill_missing_returns_none(sqlite_db):
    assert sqlite_db.update_skill("missing", 1, description="x") is None


def test_update_skill_ignores_caller_supplied_version(sqlite_db, skill_data):
    # version is server-managed: a caller-passed value never lands
    sqlite_db.create_skill(skill_data)
    updated = sqlite_db.update_skill("release-notes", 1, version=99, description="d2")
    assert updated["version"] == 2


def test_delete_skill(sqlite_db, skill_data):
    sqlite_db.create_skill(skill_data)
    assert sqlite_db.delete_skill("release-notes") is True
    assert sqlite_db.get_skill("release-notes") is None
    assert sqlite_db.delete_skill("release-notes") is False


# ============================================================================
# USER_ID OWNERSHIP TESTS (Meaning 1: nullable owner, name alone stays the key)
# ============================================================================


def test_create_skill_stores_user_id(sqlite_db, skill_data):
    created = sqlite_db.create_skill({**skill_data, "user_id": "user-a"})
    assert created["user_id"] == "user-a"
    assert sqlite_db.get_skill("release-notes")["user_id"] == "user-a"
    rows, _ = sqlite_db.get_skills()
    assert rows[0]["user_id"] == "user-a"


def test_create_skill_defaults_to_null_owner(sqlite_db, skill_data):
    created = sqlite_db.create_skill(skill_data)
    assert created["user_id"] is None
    assert sqlite_db.get_skill("release-notes")["user_id"] is None


def test_get_skill_user_filter(sqlite_db, skill_data):
    sqlite_db.create_skill({**skill_data, "user_id": "user-a"})
    assert sqlite_db.get_skill("release-notes", user_id="user-a") is not None
    assert sqlite_db.get_skill("release-notes", user_id="user-b") is None
    # None is unscoped, not a NULL-owner match
    assert sqlite_db.get_skill("release-notes") is not None


def test_get_skills_user_filter(sqlite_db, skill_data):
    sqlite_db.create_skill({**skill_data, "name": "owned-a", "user_id": "user-a"})
    sqlite_db.create_skill({**skill_data, "name": "owned-b", "user_id": "user-b"})
    sqlite_db.create_skill({**skill_data, "name": "shared"})

    rows, total = sqlite_db.get_skills(user_id="user-a")
    assert total == 1 and [r["name"] for r in rows] == ["owned-a"]

    # user_id=None is unscoped: all rows, shared included
    rows, total = sqlite_db.get_skills()
    assert total == 3 and {r["name"] for r in rows} == {"owned-a", "owned-b", "shared"}


def test_delete_skill_user_scope(sqlite_db, skill_data):
    sqlite_db.create_skill({**skill_data, "user_id": "user-a"})
    # another user's scope does not delete the row
    assert sqlite_db.delete_skill("release-notes", user_id="user-b") is False
    assert sqlite_db.get_skill("release-notes") is not None
    assert sqlite_db.delete_skill("release-notes", user_id="user-a") is True
    assert sqlite_db.get_skill("release-notes") is None


def test_same_name_different_user_rejected(sqlite_db, skill_data):
    # The Meaning-1 proof: name is globally unique on its own. A different
    # user_id does NOT make a duplicate name a distinct skill.
    sqlite_db.create_skill({**skill_data, "user_id": "user-a"})
    with pytest.raises(SkillError, match="release-notes"):
        sqlite_db.create_skill({**skill_data, "user_id": "user-b"})
    stored = sqlite_db.get_skill("release-notes")
    assert stored["user_id"] == "user-a"


# ============================================================================
# GET_SKILLS_WITH_CONTENT TESTS (the loader's read: full content, uncapped)
# ============================================================================


def test_get_skills_with_content_returns_full_rows(sqlite_db, skill_data):
    sqlite_db.create_skill(skill_data)
    sqlite_db.create_skill({**skill_data, "name": "second", "scripts": {}, "references": {}})

    rows = sqlite_db.get_skills_with_content()

    # Name-ordered, and every column present: the loader builds a full SkillRow from each
    assert [r["name"] for r in rows] == ["release-notes", "second"]
    row = rows[0]
    assert set(row.keys()) == set(SKILLS_TABLE_SCHEMA.keys())
    assert row["instructions"] == skill_data["instructions"]
    assert row["scripts"] == skill_data["scripts"]
    assert row["references"] == skill_data["references"]


def test_get_skills_with_content_is_uncapped(sqlite_db, skill_data):
    # More rows than get_skills' default page size: the loader read has no limit
    for n in range(105):
        sqlite_db.create_skill({**skill_data, "name": f"skill-{n:03d}"})
    assert len(sqlite_db.get_skills_with_content()) == 105


def test_get_skills_with_content_names_filter(sqlite_db, skill_data):
    for name in ("alpha", "beta", "gamma"):
        sqlite_db.create_skill({**skill_data, "name": name})

    rows = sqlite_db.get_skills_with_content(names=["gamma", "alpha"])
    assert [r["name"] for r in rows] == ["alpha", "gamma"]

    # A requested name with no row is not an error; the rows that exist come back
    rows = sqlite_db.get_skills_with_content(names=["beta", "missing"])
    assert [r["name"] for r in rows] == ["beta"]


def test_get_skills_with_content_user_filter(sqlite_db, skill_data):
    sqlite_db.create_skill({**skill_data, "name": "owned-a", "user_id": "user-a"})
    sqlite_db.create_skill({**skill_data, "name": "shared"})

    rows = sqlite_db.get_skills_with_content(user_id="user-a")
    assert [r["name"] for r in rows] == ["owned-a"]

    # None is unscoped: shared rows included
    assert len(sqlite_db.get_skills_with_content()) == 2


def test_get_skills_with_content_empty_db(sqlite_db):
    assert sqlite_db.get_skills_with_content() == []


def test_get_skills_with_content_postgres_outage_raises_not_empty():
    # The live-test regression: postgres _get_table swallows a connection failure and
    # returns None, which the old code read as an empty table -- one refresh during an
    # outage then wiped the skill set. An unreachable database must raise instead.
    pytest.importorskip("psycopg")
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    from agno.db.postgres import PostgresDb

    dead_engine = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:9/dead",
        connect_args={"connect_timeout": 2},
    )
    dead = PostgresDb(db_engine=dead_engine, db_schema="ai")
    with pytest.raises(OperationalError):
        dead.get_skills_with_content()


async def test_async_get_skills_with_content_postgres_outage_raises_not_empty():
    pytest.importorskip("psycopg")
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.ext.asyncio import create_async_engine

    from agno.db.postgres.async_postgres import AsyncPostgresDb

    dead_engine = create_async_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:9/dead",
        connect_args={"connect_timeout": 2},
    )
    dead = AsyncPostgresDb(db_engine=dead_engine)
    with pytest.raises(OperationalError):
        await dead.get_skills_with_content()


def test_reads_propagate_read_errors(sqlite_db, skill_data, monkeypatch):
    # A failed read raises so a refreshing loader can tell an outage from an empty
    # table. get_skill now does the same: swallowing it into None made an outage
    # indistinguishable from a missing row, so the API answered 404 while the
    # database was down. If this breaks, an outage silently wipes the skill set.
    sqlite_db.create_skill(skill_data)

    def boom():
        raise RuntimeError("database down")

    monkeypatch.setattr(sqlite_db, "Session", boom)
    with pytest.raises(RuntimeError, match="database down"):
        sqlite_db.get_skills_with_content()
    with pytest.raises(RuntimeError, match="database down"):
        sqlite_db.get_skill("release-notes")


# ============================================================================
# ASYNC SQLITE CRUD TESTS
# ============================================================================


async def test_async_create_skill_sets_version_one_and_persists(async_sqlite_db, skill_data):
    created = await async_sqlite_db.create_skill(skill_data)
    assert created["version"] == 1
    assert created["id"]

    stored = await async_sqlite_db.get_skill("release-notes")
    assert stored is not None
    assert stored["instructions"] == skill_data["instructions"]
    assert stored["scripts"] == skill_data["scripts"]
    assert stored["references"] == skill_data["references"]


async def test_async_create_skill_duplicate_name_raises_skill_error(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill(skill_data)
    with pytest.raises(SkillError, match="release-notes"):
        await async_sqlite_db.create_skill({"name": "release-notes", "description": "other", "instructions": "other"})
    stored = await async_sqlite_db.get_skill("release-notes")
    assert stored["description"] == skill_data["description"]


async def test_async_get_skills_returns_metadata_only(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill(skill_data)
    rows, total = await async_sqlite_db.get_skills()
    assert total == 1
    row = rows[0]
    assert "instructions" not in row
    assert "scripts" not in row
    assert "references" not in row
    assert row["name"] == "release-notes"


async def test_async_update_skill_checks_and_bumps_version(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill(skill_data)

    updated = await async_sqlite_db.update_skill("release-notes", 1, description="updated")
    assert updated is not None
    assert updated["version"] == 2

    stale = await async_sqlite_db.update_skill("release-notes", 1, description="stale write")
    assert stale is None
    stored = await async_sqlite_db.get_skill("release-notes")
    assert stored["description"] == "updated"


async def test_async_delete_skill(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill(skill_data)
    assert await async_sqlite_db.delete_skill("release-notes") is True
    assert await async_sqlite_db.get_skill("release-notes") is None
    assert await async_sqlite_db.delete_skill("release-notes") is False


async def test_async_stored_row_reads_back_as_content_carrying_skill(async_sqlite_db, skill_folder):
    loaded = LocalSkills(str(skill_folder)).load()[0]
    await async_sqlite_db.create_skill(_row_dict_from_path_backed_skill(loaded))

    stored = await async_sqlite_db.get_skill("release-notes")
    skill = skill_from_row(SkillRow.from_dict(stored))
    assert skill.source_path is None
    assert skill.instructions == loaded.instructions
    assert skill.script_contents == {"draft.sh": "#!/bin/sh\necho draft\n"}
    assert skill.reference_contents == {"style.md": "Keep it short.\n"}


async def test_async_user_id_filters(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill({**skill_data, "name": "owned-a", "user_id": "user-a"})
    await async_sqlite_db.create_skill({**skill_data, "name": "owned-b", "user_id": "user-b"})
    await async_sqlite_db.create_skill({**skill_data, "name": "shared"})

    assert (await async_sqlite_db.get_skill("owned-a", user_id="user-a"))["user_id"] == "user-a"
    assert await async_sqlite_db.get_skill("owned-a", user_id="user-b") is None
    assert (await async_sqlite_db.get_skill("shared"))["user_id"] is None

    rows, total = await async_sqlite_db.get_skills(user_id="user-a")
    assert total == 1 and [r["name"] for r in rows] == ["owned-a"]
    rows, total = await async_sqlite_db.get_skills()
    assert total == 3 and {r["name"] for r in rows} == {"owned-a", "owned-b", "shared"}


async def test_async_delete_skill_user_scope(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill({**skill_data, "user_id": "user-a"})
    assert await async_sqlite_db.delete_skill("release-notes", user_id="user-b") is False
    assert await async_sqlite_db.get_skill("release-notes") is not None
    assert await async_sqlite_db.delete_skill("release-notes", user_id="user-a") is True
    assert await async_sqlite_db.get_skill("release-notes") is None


async def test_async_rejects_non_string_content(async_sqlite_db, skill_data):
    with pytest.raises(SkillError, match="run.sh"):
        await async_sqlite_db.create_skill({**skill_data, "scripts": {"run.sh": 123}})
    _, total = await async_sqlite_db.get_skills()
    assert total == 0

    await async_sqlite_db.create_skill(skill_data)
    with pytest.raises(SkillError, match="bad.sh"):
        await async_sqlite_db.update_skill("release-notes", 1, scripts={"bad.sh": 1})
    stored = await async_sqlite_db.get_skill("release-notes")
    assert stored["version"] == 1 and stored["scripts"] == skill_data["scripts"]


async def test_async_same_name_different_user_rejected(async_sqlite_db, skill_data):
    # Meaning-1 proof, async side: a different user_id does not make a
    # duplicate name a distinct skill.
    await async_sqlite_db.create_skill({**skill_data, "user_id": "user-a"})
    with pytest.raises(SkillError, match="release-notes"):
        await async_sqlite_db.create_skill({**skill_data, "user_id": "user-b"})
    stored = await async_sqlite_db.get_skill("release-notes")
    assert stored["user_id"] == "user-a"


async def test_async_get_skills_with_content_returns_full_rows(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill(skill_data)
    await async_sqlite_db.create_skill({**skill_data, "name": "second", "scripts": {}, "references": {}})

    rows = await async_sqlite_db.get_skills_with_content()

    assert [r["name"] for r in rows] == ["release-notes", "second"]
    row = rows[0]
    assert set(row.keys()) == set(SKILLS_TABLE_SCHEMA.keys())
    assert row["instructions"] == skill_data["instructions"]
    assert row["scripts"] == skill_data["scripts"]
    assert row["references"] == skill_data["references"]


async def test_async_get_skills_with_content_filters(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill({**skill_data, "name": "owned-a", "user_id": "user-a"})
    await async_sqlite_db.create_skill({**skill_data, "name": "shared"})

    rows = await async_sqlite_db.get_skills_with_content(names=["owned-a", "missing"])
    assert [r["name"] for r in rows] == ["owned-a"]

    rows = await async_sqlite_db.get_skills_with_content(user_id="user-a")
    assert [r["name"] for r in rows] == ["owned-a"]

    # None is unscoped: shared rows included
    assert len(await async_sqlite_db.get_skills_with_content()) == 2


async def test_async_get_skills_with_content_propagates_read_errors(async_sqlite_db, skill_data, monkeypatch):
    await async_sqlite_db.create_skill(skill_data)

    def boom():
        raise RuntimeError("database down")

    monkeypatch.setattr(async_sqlite_db, "async_session_factory", boom)
    with pytest.raises(RuntimeError, match="database down"):
        await async_sqlite_db.get_skills_with_content()


# ============================================================================
# UPDATE_SKILL OWNERSHIP SCOPING
# ============================================================================
# user_id on update_skill is a WHERE predicate naming which row may be updated.
# It must never become a SET value: an update scoped to one user must not be able
# to rewrite another row's owner. These tests pin both halves of that.


def _owned(skill_data, name, user_id):
    return {**skill_data, "name": name, "user_id": user_id}


def test_update_skill_scoped_to_owner_updates_own_row(sqlite_db, skill_data):
    sqlite_db.create_skill(_owned(skill_data, "alice-skill", "alice"))

    updated = sqlite_db.update_skill("alice-skill", 1, user_id="alice", description="alice edited")

    assert updated is not None
    assert updated["description"] == "alice edited"
    assert updated["version"] == 2
    # The owner is untouched by a scoped update: user_id filters, it does not assign.
    assert updated["user_id"] == "alice"


def test_update_skill_scoped_to_non_owner_does_not_touch_the_row(sqlite_db, skill_data):
    sqlite_db.create_skill(_owned(skill_data, "alice-skill", "alice"))

    # Bob names the right skill at the right version, but does not own it.
    result = sqlite_db.update_skill("alice-skill", 1, user_id="bob", description="bob overwrote this")

    assert result is None
    row = sqlite_db.get_skill("alice-skill")
    assert row["description"] == skill_data["description"], "a non-owner must not write the row"
    assert row["version"] == 1, "a denied update must not bump the version"
    assert row["user_id"] == "alice", "a denied update must not reassign ownership"


def test_update_skill_scoping_never_reassigns_the_owner(sqlite_db, skill_data):
    """user_id is a WHERE predicate, not a SET value: the owner survives the update."""
    sqlite_db.create_skill(_owned(skill_data, "alice-skill", "alice"))

    sqlite_db.update_skill("alice-skill", 1, user_id="alice", description="edited")

    assert sqlite_db.get_skill("alice-skill")["user_id"] == "alice"


def test_update_skill_unscoped_is_unchanged(sqlite_db, skill_data):
    """user_id=None (the default) must behave exactly as before: no owner filter."""
    sqlite_db.create_skill(_owned(skill_data, "alice-skill", "alice"))

    updated = sqlite_db.update_skill("alice-skill", 1, description="admin edited")

    assert updated is not None
    assert updated["description"] == "admin edited"
    assert updated["version"] == 2
    assert updated["user_id"] == "alice"


def test_update_skill_scoped_on_a_null_owner_row(sqlite_db, skill_data):
    """A shared row (user_id NULL) is not owned by anyone, so a scoped update misses it."""
    sqlite_db.create_skill({**skill_data, "name": "shared-skill"})

    assert sqlite_db.get_skill("shared-skill")["user_id"] is None
    assert sqlite_db.update_skill("shared-skill", 1, user_id="alice", description="x") is None
    # Unscoped (admin) still works on it.
    assert sqlite_db.update_skill("shared-skill", 1, description="admin edit") is not None


async def test_async_update_skill_scoped_to_owner_updates_own_row(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill(_owned(skill_data, "alice-skill", "alice"))

    updated = await async_sqlite_db.update_skill("alice-skill", 1, user_id="alice", description="alice edited")

    assert updated is not None
    assert updated["description"] == "alice edited"
    assert updated["version"] == 2
    assert updated["user_id"] == "alice"


async def test_async_update_skill_scoped_to_non_owner_does_not_touch_the_row(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill(_owned(skill_data, "alice-skill", "alice"))

    result = await async_sqlite_db.update_skill("alice-skill", 1, user_id="bob", description="bob overwrote this")

    assert result is None
    row = await async_sqlite_db.get_skill("alice-skill")
    assert row["description"] == skill_data["description"]
    assert row["version"] == 1
    assert row["user_id"] == "alice"


async def test_async_update_skill_unscoped_is_unchanged(async_sqlite_db, skill_data):
    await async_sqlite_db.create_skill(_owned(skill_data, "alice-skill", "alice"))

    updated = await async_sqlite_db.update_skill("alice-skill", 1, description="admin edited")

    assert updated is not None
    assert updated["version"] == 2
    assert updated["user_id"] == "alice"


class _BackendFault(Exception):
    """Stands in for a driver/connection failure raised from inside a DB method."""


def _break_backend(monkeypatch, module_cls):
    """Make every table lookup fail the way a downed database does."""

    def boom(self, **kwargs):
        raise _BackendFault("connection refused")

    monkeypatch.setattr(module_cls, "_get_table", boom)


def test_read_write_methods_propagate_backend_faults(monkeypatch, sqlite_db, skill_data):
    """A backend fault must raise, not read as "not found".

    Swallowing it into None/([], 0)/False makes an outage indistinguishable from an absent
    row, so the API answers 404 or an empty 200 while the database is down. Mirrors
    get_skills_with_content, which already propagates for the same reason.
    """
    from agno.db.sqlite.sqlite import SqliteDb

    sqlite_db.create_skill(skill_data)
    _break_backend(monkeypatch, SqliteDb)

    with pytest.raises(_BackendFault):
        sqlite_db.get_skill(skill_data["name"])
    with pytest.raises(_BackendFault):
        sqlite_db.get_skills()
    with pytest.raises(_BackendFault):
        sqlite_db.update_skill(skill_data["name"], 1, description="x")
    with pytest.raises(_BackendFault):
        sqlite_db.delete_skill(skill_data["name"])


def test_delete_skill_returns_false_only_when_no_row_matched(sqlite_db, skill_data):
    """False must mean "nothing matched", never "the database fell over"."""
    sqlite_db.create_skill(skill_data)
    assert sqlite_db.delete_skill(skill_data["name"]) is True
    assert sqlite_db.delete_skill(skill_data["name"]) is False
    assert sqlite_db.delete_skill("never-existed") is False


@pytest.mark.asyncio
async def test_async_read_write_methods_propagate_backend_faults(monkeypatch, async_sqlite_db, skill_data):
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    await async_sqlite_db.create_skill(skill_data)

    async def boom(self, **kwargs):
        raise _BackendFault("connection refused")

    monkeypatch.setattr(AsyncSqliteDb, "_get_table", boom)

    with pytest.raises(_BackendFault):
        await async_sqlite_db.get_skill(skill_data["name"])
    with pytest.raises(_BackendFault):
        await async_sqlite_db.get_skills()
    with pytest.raises(_BackendFault):
        await async_sqlite_db.update_skill(skill_data["name"], 1, description="x")
    with pytest.raises(_BackendFault):
        await async_sqlite_db.delete_skill(skill_data["name"])


def test_sqlite_outage_preserves_last_known_good_skills(sqlite_db, skill_data, monkeypatch):
    """An outage must not read as an empty table and wipe the loaded skill set.

    The table lookup swallows a connection failure into None, which is indistinguishable
    from "the table was never created". Probing the connection tells them apart, so the
    refresh raises and Skills keeps its previous mapping. Postgres already did this.
    """
    from agno.db.sqlite.sqlite import SqliteDb
    from agno.skills import DbSkills, Skills

    sqlite_db.create_skill(skill_data)
    skills = Skills(loaders=[DbSkills(sqlite_db)])
    assert sorted(skills._skills) == [skill_data["name"]]

    def down_session():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(SqliteDb, "_get_table", lambda self, **kw: None)
    monkeypatch.setattr(sqlite_db, "Session", down_session)

    with pytest.raises(RuntimeError, match="connection refused"):
        sqlite_db.get_skills_with_content()

    skills._refresh_loaders()
    assert sorted(skills._skills) == [skill_data["name"]], "an outage wiped the last-known-good skills"


@pytest.mark.asyncio
async def test_async_sqlite_outage_propagates(async_sqlite_db, skill_data, monkeypatch):
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    await async_sqlite_db.create_skill(skill_data)

    async def no_table(self, **kwargs):
        return None

    def down_session():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(AsyncSqliteDb, "_get_table", no_table)
    monkeypatch.setattr(async_sqlite_db, "async_session_factory", down_session)

    with pytest.raises(RuntimeError, match="connection refused"):
        await async_sqlite_db.get_skills_with_content()


def test_skill_from_row_reports_the_database_as_the_source(skill_data):
    """A skill read from the table is database-backed, whatever the row says it was.

    source_type marks the path-versus-content distinction (spec 3.1), and everything
    skill_from_row builds is content-carrying. Passing the stored value through meant a skill
    created through the API reported "local" and the field stopped meaning anything after
    the first hop. The column keeps its own value as a record of where the skill was
    authored; the loaded object reports where it is being served from.
    """
    row = SkillRow.from_dict({**skill_data, "id": "abc"})
    assert row.source_type == "local"  # the column default, untouched

    assert skill_from_row(row).source_type == "db"


def test_skill_from_row_reports_db_whatever_the_row_stored(skill_data):
    """Any stored provenance still loads as db: it is being served from the table."""
    for stored in ("local", "url", "db"):
        row = SkillRow.from_dict({**skill_data, "id": "abc", "source_type": stored})
        assert skill_from_row(row).source_type == "db", f"stored={stored}"


def test_loader_serves_skills_marked_as_database_backed(sqlite_db, skill_data):
    """End to end: the loader's skills report db, not the column's default."""
    from agno.skills.loaders.db import DbSkills

    sqlite_db.create_skill(skill_data)

    loaded = DbSkills(sqlite_db).load()

    assert [s.source_type for s in loaded] == ["db"]
    # The stored row is unchanged -- only the in-memory object reports db.
    assert sqlite_db.get_skill(skill_data["name"])["source_type"] == "local"


def test_skill_row_module_does_not_import_the_sdk_layer():
    """The dependency-direction pin: db/schemas is pure data, so it must not import
    agno.skills. Row-to-Skill conversion lives in the loader instead."""
    import ast
    import inspect

    import agno.db.schemas.skills as row_module

    tree = ast.parse(inspect.getsource(row_module))
    sdk_imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.module.startswith("agno.skills")
    ]
    assert sdk_imports == []
