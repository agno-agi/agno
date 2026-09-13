"""Toolkit instructions may only name tools the configuration registers.

With versions=False the publish ladder is off the surface; with the
create_* trio off there are no create/edit/run tools; schedules are opt-in.
Prose that names a tool the model cannot call tells it to hallucinate, and
prose that asserts a draft stage that does not exist misdescribes every
write the model makes.
"""

import pytest

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.studio import StudioTools

# Every tool name any configuration can register. The invariant below holds
# for each flag combination: a name from this set that appears in the
# instructions must be registered in that configuration.
ALL_TOOL_NAMES = {
    "list_models",
    "list_tools",
    "list_functions",
    "list_knowledge",
    "list_schemas",
    "list_components",
    "get_component",
    "create_agent",
    "edit_agent",
    "run_agent",
    "create_team",
    "edit_team",
    "run_team",
    "create_workflow",
    "edit_workflow",
    "run_workflow",
    "validate_component",
    "archive_component",
    "restore_component",
    "list_versions",
    "publish_component",
    "set_current_version",
    "delete_version",
    "create_schedule",
    "update_schedule",
    "list_schedules",
    "get_schedule",
    "get_schedule_runs",
    "trigger_schedule",
    "enable_schedule",
    "disable_schedule",
    "delete_schedule",
}


def _build(tmp_path, **flags):
    db = SqliteDb(id="gating-db", db_file=str(tmp_path / "gating.db"))
    registry = Registry(name="Gating Registry", models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
    studio = StudioTools(registry=registry, db=db, **flags)
    return studio.instructions or "", set(studio.functions.keys())


class TestVersionsOff:
    def test_the_publish_ladder_is_not_named(self, tmp_path):
        instructions, registered = _build(tmp_path, versions=False)
        for name in ("publish_component", "set_current_version", "list_versions", "delete_version"):
            assert name not in registered
            assert name not in instructions

    def test_the_flat_lifecycle_is_described_instead(self, tmp_path):
        instructions, _ = _build(tmp_path, versions=False)
        assert "published immediately" in instructions
        # No prose may assert a draft stage that does not exist in this
        # configuration ("no draft stage" prose correcting the model is fine).
        for stale in ("a draft, unless publish=true", "Drafts are private", "preview a draft"):
            assert stale not in instructions

    def test_versions_on_still_describes_the_ladder(self, tmp_path):
        instructions, registered = _build(tmp_path, versions=True)
        assert "publish_component" in instructions
        assert "publish_component" in registered
        assert "unless publish=true" in instructions


class TestAuthoringOff:
    def test_no_compose_or_run_prose_without_authoring_tools(self, tmp_path):
        instructions, registered = _build(tmp_path, create_agents=False, create_teams=False, create_workflows=False)
        assert not any(name.startswith(("create_", "edit_", "run_")) for name in registered)
        assert "Compose" not in instructions
        assert "Run tools" not in instructions
        assert "lifecycle" not in instructions


class TestSchedules:
    def test_schedule_tools_come_with_schedule_prose(self, tmp_path):
        instructions, registered = _build(tmp_path, schedules=True)
        assert "create_schedule" in registered
        assert "create_schedule" in instructions
        assert "trigger_schedule" in instructions

    def test_no_schedule_prose_without_the_tools(self, tmp_path):
        instructions, registered = _build(tmp_path)
        assert "create_schedule" not in registered
        assert "create_schedule" not in instructions


class TestEveryNamedToolIsRegistered:
    @pytest.mark.parametrize(
        "flags",
        [
            {},
            {"versions": False},
            {"schedules": True},
            {"versions": False, "schedules": True},
            {"create_agents": False, "create_teams": False, "create_workflows": False},
            {"create_agents": False, "create_teams": False, "create_workflows": False, "versions": False},
        ],
    )
    def test_instructions_never_name_an_unregistered_tool(self, tmp_path, flags):
        instructions, registered = _build(tmp_path, **flags)
        named = {name for name in ALL_TOOL_NAMES if name in instructions}
        assert named <= registered, f"instructions name unregistered tools: {sorted(named - registered)}"


class TestProseNamesOnlyBuildableTypes:
    """The lifecycle sentence must not advertise a type this palette cannot build."""

    def _prose(self, tmp_path, **flags):
        instructions, registered = _build(tmp_path, **flags)
        text = instructions if isinstance(instructions, str) else "\n".join(str(line) for line in instructions)
        compose = next((line for line in text.splitlines() if "Compose" in line), "")
        return compose, registered

    def test_a_workflows_only_palette_does_not_advertise_agents_or_teams(self, tmp_path):
        compose, registered = self._prose(tmp_path, create_agents=False, create_teams=False, create_workflows=True)

        assert "create_workflow" in registered
        assert "create_agent" not in registered and "create_team" not in registered
        assert "Compose workflows from" in compose
        assert "agents" not in compose and "teams" not in compose

    def test_an_agents_only_palette_names_only_agents(self, tmp_path):
        compose, registered = self._prose(tmp_path, create_agents=True, create_teams=False, create_workflows=False)

        assert "create_agent" in registered
        assert "Compose agents from" in compose
        assert "teams" not in compose and "workflows" not in compose

    def test_a_two_type_palette_reads_naturally(self, tmp_path):
        compose, _ = self._prose(tmp_path, create_agents=True, create_teams=True, create_workflows=False)

        assert "Compose agents and teams from" in compose

    def test_the_full_palette_still_names_all_three(self, tmp_path):
        compose, _ = self._prose(tmp_path)

        assert "Compose agents, teams, and workflows from" in compose

    def test_the_flat_lifecycle_variant_is_gated_the_same_way(self, tmp_path):
        compose, _ = self._prose(
            tmp_path, create_agents=False, create_teams=False, create_workflows=True, versions=False
        )

        assert "Compose workflows from" in compose
        assert "agents" not in compose and "teams" not in compose
