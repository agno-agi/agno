"""Skills stored as versioned components, and agents and teams that reference them."""

from pathlib import Path

import pytest

from agno.agent import Agent
from agno.db.base import ComponentDependencyError, ComponentType
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.skills import DbSkills, LocalSkillExecutor, LocalSkills, Skill, SkillRef, Skills
from agno.skills.component import MAX_SKILL_CONTENT_BYTES, skill_to_config
from agno.skills.errors import SkillValidationError
from agno.team import Team


@pytest.fixture
def db(tmp_path) -> SqliteDb:
    return SqliteDb(db_file=str(tmp_path / "skills.db"))


def make_skill(instructions: str = "v1", name: str = "pdf-extract") -> Skill:
    return Skill(
        name=name,
        description="Extract text from PDFs",
        instructions=instructions,
        scripts=["run.py"],
        references=["guide.md"],
        script_contents={"run.py": "#!/usr/bin/env python3\nprint('hi')\n"},
        reference_contents={"guide.md": "# Guide"},
    )


def db_skills(db: SqliteDb, *refs) -> Skills:
    return Skills(loaders=[DbSkills(db, list(refs))])


def link_rows(db: SqliteDb, component_id: str, version: int = 1):
    return [
        (row["link_kind"], row["child_component_id"], row["child_version"])
        for row in db.get_links(component_id=component_id, version=version)
    ]


class TestSkillComponent:
    def test_every_save_appends_a_published_version(self, db):
        skill = make_skill("v1")
        assert skill.save(db=db) == 1
        skill.instructions = "v2"
        assert skill.save(db=db) == 2

        assert Skill.load("pdf-extract", db=db).instructions == "v2"
        old = Skill.load("pdf-extract", db=db, version=1)
        assert old.instructions == "v1"
        assert old.script_contents == {"run.py": "#!/usr/bin/env python3\nprint('hi')\n"}
        assert old.reference_contents == {"guide.md": "# Guide"}
        assert old.source_type == "db"
        assert old.id == "pdf-extract"
        assert db.get_component("pdf-extract")["component_type"] == ComponentType.SKILL.value

    def test_explicit_id_and_owner(self, db):
        skill = make_skill()
        skill.id = "pdf-extract-alice"
        skill.save(db=db, user_id="alice")

        assert db.get_component("pdf-extract-alice")["user_id"] == "alice"
        assert Skill.load("pdf-extract-alice", db=db).name == "pdf-extract"
        # Save publishes, and a published skill is visible to every user.
        assert Skill.load("pdf-extract-alice", db=db, user_id="bob") is not None

    def test_path_backed_skill_is_stored_with_its_file_contents(self, db, tmp_path: Path):
        folder = tmp_path / "skills" / "local-skill"
        (folder / "scripts").mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: local-skill\ndescription: From disk\n---\nDo the thing")
        (folder / "scripts" / "go.sh").write_text("#!/bin/sh\necho go\n")
        skill = LocalSkills(str(folder)).load()[0]

        skill.save(db=db)
        folder.joinpath("scripts", "go.sh").unlink()

        loaded = Skill.load("local-skill", db=db)
        assert loaded.source_path is None
        assert loaded.script_contents == {"go.sh": "#!/bin/sh\necho go\n"}

    def test_oversized_skill_is_refused(self, db):
        skill = make_skill("x" * (MAX_SKILL_CONTENT_BYTES + 1))
        with pytest.raises(SkillValidationError, match="at most"):
            skill.save(db=db)
        assert db.get_component("pdf-extract") is None

    def test_invalid_name_is_refused(self, db):
        with pytest.raises(SkillValidationError):
            make_skill(name="Not A Valid Name").save(db=db)

    def test_load_ignores_a_component_of_another_type(self, db):
        Agent(id="pdf-extract", name="pdf-extract").save(db=db)
        assert Skill.load("pdf-extract", db=db) is None

    def test_delete_refuses_while_referenced(self, db):
        skill = make_skill()
        skill.save(db=db)
        Agent(id="a1", name="A1", skills=db_skills(db, "pdf-extract")).save(db=db)

        with pytest.raises(ComponentDependencyError):
            skill.delete(db=db)

        Agent(id="a1").delete(db=db, hard_delete=True)
        assert skill.delete(db=db) is True


class TestDbSkills:
    def test_resolves_pinned_and_current_versions(self, db):
        skill = make_skill("v1")
        skill.save(db=db)
        skill.instructions = "v2"
        skill.save(db=db)
        make_skill("other", name="other-skill").save(db=db)

        loader = DbSkills(db, [SkillRef("pdf-extract", version=1), "other-skill"])
        skills = Skills(loaders=[loader])

        assert skills.get_skill("pdf-extract").instructions == "v1"
        assert loader.resolved_versions == {"pdf-extract": 1, "other-skill": 1}

    def test_missing_skill_is_skipped_and_recorded(self, db):
        loader = DbSkills(db, ["nope"])
        assert Skills(loaders=[loader]).get_skill_names() == []
        assert [ref.id for ref in loader.missing] == ["nope"]

    def test_duplicate_references_are_refused(self, db):
        with pytest.raises(ValueError, match="more than once"):
            DbSkills(db, ["pdf-extract", SkillRef("pdf-extract", version=1)])

    def test_owner_scope_hides_another_users_unpublished_skill(self, db):
        db.upsert_component(component_id="private", component_type=ComponentType.SKILL, user_id="alice")
        db.upsert_config(component_id="private", config=skill_to_config(make_skill(name="private")), stage="draft")

        loader = DbSkills(db, ["private"], user_id="bob")
        Skills(loaders=[loader])
        assert [ref.id for ref in loader.missing] == ["private"]

    @pytest.mark.parametrize("version", [0, -1, True, "v1"])
    def test_invalid_selector_is_refused(self, version):
        with pytest.raises(ValueError):
            SkillRef("pdf-extract", version=version)


class TestAgentSkillReferences:
    def test_unversioned_reference_pins_the_loaded_version(self, db):
        skill = make_skill("v1")
        skill.save(db=db)
        agent = Agent(id="a1", name="A1", skills=db_skills(db, "pdf-extract"))
        # A newer version published after the agent loaded its skills is not what it was tested with.
        skill.instructions = "v2"
        skill.save(db=db)

        agent.save(db=db)

        assert db.get_config("a1")["config"]["skills"] == {"refs": [{"skill_id": "pdf-extract", "version": 1}]}
        assert link_rows(db, "a1") == [("skill", "pdf-extract", 1)]
        assert Agent.load("a1", db=db, strict=True).skills.get_skill("pdf-extract").instructions == "v1"

    def test_latest_reference_follows_the_current_version(self, db):
        skill = make_skill("v1")
        skill.save(db=db)
        Agent(id="a1", name="A1", skills=db_skills(db, SkillRef("pdf-extract", version="latest"))).save(db=db)
        skill.instructions = "v2"
        skill.save(db=db)

        assert link_rows(db, "a1") == [("skill", "pdf-extract", None)]
        assert Agent.load("a1", db=db, strict=True).skills.get_skill("pdf-extract").instructions == "v2"

    def test_save_refuses_an_unknown_skill_before_writing(self, db):
        agent = Agent(id="a1", name="A1", skills=db_skills(db, SkillRef("nope", version=1)))
        with pytest.raises(ValueError, match="not a stored skill"):
            agent.save(db=db)
        assert db.get_component("a1") is None

    def test_strict_load_refuses_a_missing_version_and_lenient_skips_it(self, db):
        make_skill().save(db=db)
        Agent(id="a1", name="A1", skills=db_skills(db, "pdf-extract")).save(db=db)
        # Simulate a pin that no longer resolves.
        config = db.get_config("a1")["config"]
        config["skills"]["refs"][0]["version"] = 9
        db.upsert_config(component_id="a1", config=config, stage="published")

        with pytest.raises(ComponentRehydrationError, match="not published"):
            Agent.load("a1", db=db, strict=True)
        assert Agent.load("a1", db=db).skills.get_skill_names() == []

    def test_db_argument_resolves_skills_when_the_config_has_no_db(self, db):
        make_skill().save(db=db)
        config = Agent(id="a1", name="A1", skills=db_skills(db, SkillRef("pdf-extract", version=1))).to_dict()
        config.pop("db", None)

        assert Agent.from_dict(config, db=db, strict=True).skills.get_skill_names() == ["pdf-extract"]
        with pytest.raises(ComponentRehydrationError, match="no database"):
            Agent.from_dict(config, strict=True)

    def test_custom_executor_is_never_replaced_by_the_host_executor(self, db):
        class SandboxExecutor(LocalSkillExecutor):
            pass

        make_skill().save(db=db)
        skills = Skills(loaders=[DbSkills(db, ["pdf-extract"])], executor=SandboxExecutor())
        Agent(id="a1", name="A1", skills=skills).save(db=db)

        with pytest.raises(ComponentRehydrationError, match="custom skill executor"):
            Agent.load("a1", db=db, strict=True)
        assert Agent.load("a1", db=db).skills is None

    def test_local_skills_are_not_saved(self, db, tmp_path: Path):
        folder = tmp_path / "local-skill"
        folder.mkdir()
        (folder / "SKILL.md").write_text("---\nname: local-skill\ndescription: From disk\n---\nBody")
        agent = Agent(id="a1", name="A1", skills=Skills(loaders=[LocalSkills(str(folder))]))

        assert "skills" not in agent.to_dict()

    def test_stored_skill_script_runs_from_its_content(self, db):
        Skill(
            name="hello",
            description="Says hello",
            instructions="Run hello.py",
            scripts=["hello.py"],
            script_contents={"hello.py": "#!/usr/bin/env python3\nimport sys\nprint('hi', *sys.argv[1:])\n"},
            reference_contents={},
        ).save(db=db)
        Agent(id="a1", name="A1", skills=db_skills(db, "hello")).save(db=db)

        agent = Agent.load("a1", db=db, strict=True)
        result = agent.skills._get_skill_script("hello", "hello.py", execute=True, args=["there"])

        assert '"stdout": "hi there\\n"' in result


class TestTeamSkillReferences:
    def test_team_saves_and_loads_skills_next_to_members(self, db):
        skill = make_skill("v1")
        skill.save(db=db)
        team = Team(
            id="t1",
            name="T1",
            members=[Agent(id="m1", name="M1")],
            skills=db_skills(db, SkillRef("pdf-extract", version="latest")),
        )
        team.save(db=db)
        skill.instructions = "v2"
        skill.save(db=db)

        assert sorted(link_rows(db, "t1")) == [("member", "m1", 1), ("skill", "pdf-extract", None)]
        loaded = Team.load("t1", db=db, strict=True)
        assert [member.id for member in loaded.members] == ["m1"]
        assert loaded.skills.get_skill("pdf-extract").instructions == "v2"
