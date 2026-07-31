"""Unit tests for Skills orchestrator class."""

import json
from pathlib import Path
from typing import ClassVar, List, Optional

import pytest

from agno.skills.agent_skills import Skills
from agno.skills.errors import SkillError, SkillValidationError
from agno.skills.executor import LocalSkillExecutor, SkillExecutor
from agno.skills.loaders.base import SkillLoader
from agno.skills.loaders.local import LocalSkills
from agno.skills.skill import Skill
from agno.skills.utils import ScriptResult
from agno.tools.function import Function

from .conftest import MockSkillLoader

# The exact snippet produced by the `mock_loader_multiple` fixture (sample_skill, then
# minimal_skill). Pinned verbatim so any edit to the preamble or the per-skill block is a
# deliberate update here, not an accidental prompt change: this text ships in every request's
# system message, so changing it also busts provider-side prompt caches for every user.
EXPECTED_SYSTEM_PROMPT_SNIPPET = """<skills_system>

## What are Skills?
Skills are packages of domain expertise that extend your capabilities. Each skill contains:
- **Instructions**: Detailed guidance on when and how to apply the skill
- **Scripts**: Executable code templates you can use or adapt
- **References**: Supporting documentation (guides, cheatsheets, examples)

## IMPORTANT: How to Use Skills
**Skill names are NOT callable functions.** You cannot call a skill directly by its name.
Instead, you MUST use the provided skill access tools:

1. `get_skill_instructions(skill_name)` - Load the full instructions for a skill
2. `get_skill_reference(skill_name, reference_path)` - Access specific documentation
3. `get_skill_script(skill_name, script_path, execute=False)` - Read or run scripts

## Progressive Discovery Workflow
1. **Browse**: Review the skill summaries below to understand what's available
2. **Load**: When a task matches a skill, call `get_skill_instructions(skill_name)` first
3. **Reference**: Use `get_skill_reference` to access specific documentation as needed
4. **Scripts**: Use `get_skill_script` to read or execute scripts from a skill

**IMPORTANT**: References are documentation files (NOT executable). Only use `get_skill_script` when `<scripts>` lists actual script files. If `<scripts>none</scripts>`, do NOT call `get_skill_script`.

This approach ensures you only load detailed instructions when actually needed.

## Available Skills
<skill>
  <name>test-skill</name>
  <description>A test skill for unit testing</description>
  <scripts>helper.py, runner.sh</scripts>
  <references>guide.md, api-docs.md</references>
</skill>
<skill>
  <name>minimal-skill</name>
  <description>A minimal skill</description>
  <scripts>none</scripts>
</skill>

</skills_system>"""

# --- Initialization Tests ---


def test_skills_with_single_loader(mock_loader: MockSkillLoader) -> None:
    """Test Skills initialization with a single loader."""
    skills = Skills(loaders=[mock_loader])
    assert len(skills.loaders) == 1


def test_skills_with_multiple_loaders(mock_loader: MockSkillLoader, mock_loader_empty: MockSkillLoader) -> None:
    """Test Skills initialization with multiple loaders."""
    skills = Skills(loaders=[mock_loader, mock_loader_empty])
    assert len(skills.loaders) == 2


def test_skills_empty_loaders() -> None:
    """Test Skills initialization with no loaders."""
    skills = Skills(loaders=[])
    assert len(skills.loaders) == 0


# --- Eager Loading Tests ---


def test_skills_loaded_on_init(mock_loader: MockSkillLoader) -> None:
    """Test that skills are loaded immediately on initialization."""
    skills = Skills(loaders=[mock_loader])
    # Skills should be loaded immediately
    assert len(skills._skills) > 0
    assert "test-skill" in skills._skills


def test_reload_clears_and_reloads(sample_skill: Skill) -> None:
    """Test that reload() replaces the existing skills with what the loaders now return."""
    from .conftest import MockSkillLoader

    loader = MockSkillLoader([sample_skill])
    skills = Skills(loaders=[loader])

    # Initial load happens in __init__
    assert len(skills._skills) == 1
    assert "test-skill" in skills._skills

    # Update the loader with a different skill
    new_skill = Skill(
        name="new-skill",
        description="A new skill",
        instructions="New instructions",
        source_path="/new/path",
    )
    loader._skills = [new_skill]

    # Reload should replace the mapping
    skills.reload()
    assert "new-skill" in skills._skills
    assert "test-skill" not in skills._skills


class PeekingLoader(SkillLoader):
    """A loader that records the Skills mapping as it looked while the loader was running."""

    def __init__(self, skills: List[Skill]):
        self._skills = skills
        self.observed: Optional[Skills] = None
        self.names_seen_while_loading: List[List[str]] = []

    def load(self) -> List[Skill]:
        if self.observed is not None:
            self.names_seen_while_loading.append(self.observed.get_skill_names())
        return self._skills


def test_reload_never_exposes_empty_skill_set(sample_skill: Skill, minimal_skill: Skill) -> None:
    """Test that a reader running during a reload sees the old skills, never an empty set."""
    loader = PeekingLoader([sample_skill])
    skills = Skills(loaders=[loader])

    # Only observe from here, so the initial (genuinely empty) load is not counted.
    loader.observed = skills
    loader._skills = [sample_skill, minimal_skill]
    skills.reload()

    assert loader.names_seen_while_loading == [["test-skill"]]
    assert skills.get_skill_names() == ["test-skill", "minimal-skill"]


def test_reload_twice_never_exposes_empty_skill_set(sample_skill: Skill, minimal_skill: Skill) -> None:
    """Test that the second reload also sees a populated mapping, not leftovers from the first."""
    loader = PeekingLoader([sample_skill])
    skills = Skills(loaders=[loader])
    loader.observed = skills

    skills.reload()
    loader._skills = [minimal_skill]
    skills.reload()

    assert loader.names_seen_while_loading == [["test-skill"], ["test-skill"]]
    assert skills.get_skill_names() == ["minimal-skill"]


# --- Duplicate Name Tests ---


def _duplicate_loaders() -> List[MockSkillLoader]:
    return [
        MockSkillLoader([Skill(name="duplicate", description="First", instructions="First", source_path="/path1")]),
        MockSkillLoader([Skill(name="duplicate", description="Second", instructions="Second", source_path="/path2")]),
    ]


def test_on_duplicate_warn_keeps_last(sample_skill: Skill) -> None:
    """Test that on_duplicate='warn' keeps the last loaded skill, matching the default."""
    skills = Skills(loaders=_duplicate_loaders(), on_duplicate="warn")

    assert [s.description for s in skills.get_all_skills()] == ["Second"]


def test_on_duplicate_raise_names_skill_and_loader() -> None:
    """Test that on_duplicate='raise' rejects the collision, naming the skill and the loader."""
    loaders = _duplicate_loaders()

    with pytest.raises(SkillError) as exc_info:
        Skills(loaders=loaders, on_duplicate="raise")

    message = str(exc_info.value)
    assert "duplicate" in message
    assert repr(loaders[1]) in message


def test_on_duplicate_raise_on_reload() -> None:
    """Test that on_duplicate='raise' still rejects a collision introduced by a reload."""
    loaders = _duplicate_loaders()
    loaders[1]._skills = []
    skills = Skills(loaders=loaders, on_duplicate="raise")

    loaders[1]._skills = [Skill(name="duplicate", description="Second", instructions="s", source_path="/p2")]
    with pytest.raises(SkillError):
        skills.reload()


def test_on_duplicate_rejects_unknown_value(mock_loader: MockSkillLoader) -> None:
    """Test that an unrecognized on_duplicate value is rejected instead of silently ignored."""
    with pytest.raises(ValueError) as exc_info:
        Skills(loaders=[mock_loader], on_duplicate="ignore")  # type: ignore[arg-type]

    assert "on_duplicate" in str(exc_info.value)


# --- Retrieval Tests ---


def test_get_skill_by_name(mock_loader: MockSkillLoader) -> None:
    """Test getting a skill by name."""
    skills = Skills(loaders=[mock_loader])
    skill = skills.get_skill("test-skill")

    assert skill is not None
    assert skill.name == "test-skill"


def test_get_skill_not_found(mock_loader: MockSkillLoader) -> None:
    """Test getting a non-existent skill returns None."""
    skills = Skills(loaders=[mock_loader])
    skill = skills.get_skill("nonexistent-skill")

    assert skill is None


def test_get_all_skills(mock_loader_multiple: MockSkillLoader) -> None:
    """Test getting all skills."""
    skills = Skills(loaders=[mock_loader_multiple])
    all_skills = skills.get_all_skills()

    assert len(all_skills) == 2
    assert all(isinstance(s, Skill) for s in all_skills)


def test_get_all_skills_empty(mock_loader_empty: MockSkillLoader) -> None:
    """Test getting all skills when none loaded."""
    skills = Skills(loaders=[mock_loader_empty])
    all_skills = skills.get_all_skills()

    assert all_skills == []


def test_get_skill_names(mock_loader_multiple: MockSkillLoader) -> None:
    """Test getting skill names."""
    skills = Skills(loaders=[mock_loader_multiple])
    names = skills.get_skill_names()

    assert len(names) == 2
    assert "test-skill" in names
    assert "minimal-skill" in names


def test_get_skill_names_empty(mock_loader_empty: MockSkillLoader) -> None:
    """Test getting skill names when none loaded."""
    skills = Skills(loaders=[mock_loader_empty])
    names = skills.get_skill_names()

    assert names == []


# --- Multiple Loaders Tests ---


def test_skills_from_multiple_loaders(sample_skill: Skill, minimal_skill: Skill) -> None:
    """Test loading skills from multiple loaders."""
    loader1 = MockSkillLoader([sample_skill])
    loader2 = MockSkillLoader([minimal_skill])

    skills = Skills(loaders=[loader1, loader2])
    all_skills = skills.get_all_skills()

    assert len(all_skills) == 2
    names = {s.name for s in all_skills}
    assert "test-skill" in names
    assert "minimal-skill" in names


def test_duplicate_skill_name_overwrites(sample_skill: Skill) -> None:
    """Test that duplicate skill names cause overwriting."""
    skill1 = Skill(
        name="duplicate",
        description="First version",
        instructions="First",
        source_path="/path1",
    )
    skill2 = Skill(
        name="duplicate",
        description="Second version",
        instructions="Second",
        source_path="/path2",
    )

    loader1 = MockSkillLoader([skill1])
    loader2 = MockSkillLoader([skill2])

    skills = Skills(loaders=[loader1, loader2])
    all_skills = skills.get_all_skills()

    assert len(all_skills) == 1
    assert all_skills[0].description == "Second version"


# --- System Prompt Tests ---


def test_get_system_prompt_snippet_matches_golden(mock_loader_multiple: MockSkillLoader) -> None:
    """Test that the snippet matches its pinned text exactly."""
    skills = Skills(loaders=[mock_loader_multiple])

    assert skills.get_system_prompt_snippet() == EXPECTED_SYSTEM_PROMPT_SNIPPET


def test_get_system_prompt_snippet_format(mock_loader: MockSkillLoader) -> None:
    """Test system prompt snippet format."""
    skills = Skills(loaders=[mock_loader])
    snippet = skills.get_system_prompt_snippet()

    assert "<skills_system>" in snippet
    assert "</skills_system>" in snippet
    assert "<skill>" in snippet
    assert "</skill>" in snippet


def test_get_system_prompt_snippet_empty(mock_loader_empty: MockSkillLoader) -> None:
    """Test system prompt snippet when no skills loaded."""
    skills = Skills(loaders=[mock_loader_empty])
    snippet = skills.get_system_prompt_snippet()

    assert snippet == ""


def test_get_system_prompt_includes_skill_name(mock_loader: MockSkillLoader) -> None:
    """Test that system prompt includes skill name."""
    skills = Skills(loaders=[mock_loader])
    snippet = skills.get_system_prompt_snippet()

    assert "<name>test-skill</name>" in snippet


def test_get_system_prompt_includes_description(mock_loader: MockSkillLoader) -> None:
    """Test that system prompt includes skill description."""
    skills = Skills(loaders=[mock_loader])
    snippet = skills.get_system_prompt_snippet()

    assert "A test skill for unit testing" in snippet


def test_get_system_prompt_includes_scripts(mock_loader: MockSkillLoader) -> None:
    """Test that system prompt includes scripts list."""
    skills = Skills(loaders=[mock_loader])
    snippet = skills.get_system_prompt_snippet()

    assert "<scripts>" in snippet
    assert "helper.py" in snippet


def test_get_system_prompt_shows_none_when_no_scripts(minimal_skill: Skill) -> None:
    """Test that system prompt shows <scripts>none</scripts> when skill has no scripts."""
    loader = MockSkillLoader([minimal_skill])
    skills = Skills(loaders=[loader])
    snippet = skills.get_system_prompt_snippet()

    # Should explicitly show "none" instead of omitting the tag
    assert "<scripts>none</scripts>" in snippet


def test_get_system_prompt_includes_references(mock_loader: MockSkillLoader) -> None:
    """Test that system prompt includes references list."""
    skills = Skills(loaders=[mock_loader])
    snippet = skills.get_system_prompt_snippet()

    assert "<references>" in snippet
    assert "guide.md" in snippet


def test_get_system_prompt_includes_progressive_discovery(mock_loader: MockSkillLoader) -> None:
    """Test that system prompt includes progressive discovery section."""
    skills = Skills(loaders=[mock_loader])
    snippet = skills.get_system_prompt_snippet()

    assert "Progressive Discovery" in snippet
    assert "get_skill_instructions" in snippet
    assert "get_skill_reference" in snippet
    assert "get_skill_script" in snippet


# --- Per-Request Refresh Tests ---


class CountingLoader(SkillLoader):
    """A loader that counts its load() calls and can be told to fail."""

    def __init__(self, skills: List[Skill]):
        self._skills = skills
        self.load_count = 0
        self.fail = False

    def load(self) -> List[Skill]:
        self.load_count += 1
        if self.fail:
            raise RuntimeError("database down")
        return list(self._skills)


class RefreshingLoader(CountingLoader):
    """A CountingLoader marked for per-request refresh, like DbSkills."""

    refresh_per_request: ClassVar[bool] = True


def test_snippet_refreshes_marked_loaders_per_request(sample_skill: Skill, minimal_skill: Skill) -> None:
    """Test that a refresh_per_request loader's changes appear in the next snippet without reload()."""
    loader = RefreshingLoader([sample_skill])
    skills = Skills(loaders=[loader])

    assert "minimal-skill" not in skills.get_system_prompt_snippet()
    loader._skills = [sample_skill, minimal_skill]
    assert "minimal-skill" in skills.get_system_prompt_snippet()


def test_snippet_does_not_rerun_unmarked_loaders(sample_skill: Skill) -> None:
    """Test that a plain loader is loaded once, not re-run on every snippet build."""
    loader = CountingLoader([sample_skill])
    skills = Skills(loaders=[loader])

    skills.get_system_prompt_snippet()
    skills.get_system_prompt_snippet()

    assert loader.load_count == 1


def test_refresh_merges_unmarked_loader_results_from_cache(sample_skill: Skill, minimal_skill: Skill) -> None:
    """Test that a refresh re-reads only the marked loader and keeps the others' cached skills."""
    static = CountingLoader([sample_skill])
    refreshing = RefreshingLoader([minimal_skill])
    skills = Skills(loaders=[static, refreshing])

    # If the refresh re-ran the static loader, its skill would vanish here.
    static._skills = []
    snippet = skills.get_system_prompt_snippet()

    assert "test-skill" in snippet
    assert "minimal-skill" in snippet
    assert static.load_count == 1


def test_failed_refresh_keeps_last_loaded_skills(sample_skill: Skill) -> None:
    """Test that a snippet built while the refresh fails serves the last loaded skills."""
    loader = RefreshingLoader([sample_skill])
    skills = Skills(loaders=[loader])

    loader.fail = True
    # Twice: the second request must also serve the cached mapping, not an empty one.
    assert "test-skill" in skills.get_system_prompt_snippet()
    assert "test-skill" in skills.get_system_prompt_snippet()


def test_refresh_recovers_after_failure(sample_skill: Skill, minimal_skill: Skill) -> None:
    """Test that the mapping self-corrects on the next successful refresh."""
    loader = RefreshingLoader([sample_skill])
    skills = Skills(loaders=[loader])

    loader.fail = True
    assert "test-skill" in skills.get_system_prompt_snippet()

    loader.fail = False
    loader._skills = [minimal_skill]
    snippet = skills.get_system_prompt_snippet()
    assert "minimal-skill" in snippet
    assert "test-skill" not in snippet


def test_refresh_collision_under_raise_keeps_old_mapping(sample_skill: Skill) -> None:
    """Test that a duplicate introduced by a refresh keeps the old mapping instead of raising mid-request."""
    static = MockSkillLoader([sample_skill])
    refreshing = RefreshingLoader([])
    skills = Skills(loaders=[static, refreshing], on_duplicate="raise")

    refreshing._skills = [Skill(name="test-skill", description="Colliding", instructions="i", source_path="/p2")]
    snippet = skills.get_system_prompt_snippet()

    assert "A test skill for unit testing" in snippet
    assert "Colliding" not in snippet


# --- Async Refresh Twin Tests ---


class AsyncRefreshingLoader(RefreshingLoader):
    """A RefreshingLoader with a counted async load, like DbSkills on an async backend."""

    def __init__(self, skills: List[Skill]):
        super().__init__(skills)
        self.aload_count = 0

    async def aload(self) -> List[Skill]:
        self.aload_count += 1
        if self.fail:
            raise RuntimeError("database down")
        return list(self._skills)


async def test_async_snippet_refreshes_through_aload(sample_skill: Skill, minimal_skill: Skill) -> None:
    """Test that aget_system_prompt_snippet refreshes through aload, not the sync load."""
    loader = AsyncRefreshingLoader([sample_skill])
    skills = Skills(loaders=[loader])

    loader._skills = [sample_skill, minimal_skill]
    assert "minimal-skill" in await skills.aget_system_prompt_snippet()
    assert loader.aload_count == 1
    assert loader.load_count == 1  # only the eager constructor load


async def test_aload_default_delegates_to_sync_load(sample_skill: Skill) -> None:
    """Test that a refresh loader without its own aload still refreshes, through the sync load."""
    loader = RefreshingLoader([sample_skill])
    skills = Skills(loaders=[loader])

    assert "test-skill" in await skills.aget_system_prompt_snippet()
    assert loader.load_count == 2  # the constructor load, then aload's sync delegate


async def test_failed_async_refresh_keeps_last_loaded_skills(sample_skill: Skill) -> None:
    """Test that a snippet built while the async refresh fails serves the last loaded skills."""
    loader = AsyncRefreshingLoader([sample_skill])
    skills = Skills(loaders=[loader])

    loader.fail = True
    # Twice: the second request must also serve the cached mapping, not an empty one.
    assert "test-skill" in await skills.aget_system_prompt_snippet()
    assert "test-skill" in await skills.aget_system_prompt_snippet()


async def test_async_and_sync_snippets_render_the_same(mock_loader_multiple: MockSkillLoader) -> None:
    """Test that the twins render the same snippet from the same mapping."""
    skills = Skills(loaders=[mock_loader_multiple])

    assert await skills.aget_system_prompt_snippet() == skills.get_system_prompt_snippet()


async def test_overlapping_async_refreshes_keep_the_newer_state(sample_skill: Skill, minimal_skill: Skill) -> None:
    """Test that an older in-flight refresh cannot commit over a newer one's result."""
    import asyncio

    class GatedLoader(AsyncRefreshingLoader):
        """First aload reads its data, then parks on a gate before returning."""

        def __init__(self, skills: List[Skill]):
            super().__init__(skills)
            self.gate = asyncio.Event()

        async def aload(self) -> List[Skill]:
            self.aload_count += 1
            snapshot = list(self._skills)
            if self.aload_count == 1:
                await self.gate.wait()
            return snapshot

    loader = GatedLoader([sample_skill])
    skills = Skills(loaders=[loader])

    first = asyncio.create_task(skills.aget_system_prompt_snippet())
    await asyncio.sleep(0.01)  # let the first refresh start and park mid-await
    loader._skills = [minimal_skill]
    second = asyncio.create_task(skills.aget_system_prompt_snippet())
    await asyncio.sleep(0.01)
    loader.gate.set()
    await first
    await second

    assert skills.get_skill_names() == ["minimal-skill"]


# --- Get Tools Tests ---


def test_get_tools_returns_functions(mock_loader: MockSkillLoader) -> None:
    """Test that get_tools returns a list of Function objects."""
    skills = Skills(loaders=[mock_loader])
    tools = skills.get_tools()

    assert isinstance(tools, list)
    assert all(isinstance(t, Function) for t in tools)


def test_get_tools_returns_three_functions(mock_loader: MockSkillLoader) -> None:
    """Test that get_tools returns exactly three functions."""
    skills = Skills(loaders=[mock_loader])
    tools = skills.get_tools()

    assert len(tools) == 3
    tool_names = {t.name for t in tools}
    assert "get_skill_instructions" in tool_names
    assert "get_skill_reference" in tool_names
    assert "get_skill_script" in tool_names


def test_get_skill_script_tool_accepts_null_path(mock_loader: MockSkillLoader) -> None:
    """Regression: calling the tool with script_path=None must not raise.

    Agno wraps every tool entrypoint with pydantic's validate_call. When
    script_path was a required str, a model emitting script_path=null produced
    a ValidationError at the tool boundary instead of the function's own
    graceful JSON error. Exercise the wrapped entrypoint the same way Function
    does and assert it returns a JSON error string.
    """
    skills = Skills(loaders=[mock_loader])
    tool = next(t for t in skills.get_tools() if t.name == "get_skill_script")
    tool.process_entrypoint()

    result = json.loads(tool.entrypoint(skill_name="test-skill", script_path=None))
    assert "error" in result
    assert "script_path is required" in result["error"]


def test_get_skill_reference_tool_accepts_null_path(mock_loader: MockSkillLoader) -> None:
    """Regression: calling the tool with reference_path=None must not raise."""
    skills = Skills(loaders=[mock_loader])
    tool = next(t for t in skills.get_tools() if t.name == "get_skill_reference")
    tool.process_entrypoint()

    result = json.loads(tool.entrypoint(skill_name="test-skill", reference_path=None))
    assert "error" in result
    assert "reference_path is required" in result["error"]


# --- Skill Instructions Tool Tests ---


def test_get_skill_instructions_success(mock_loader: MockSkillLoader) -> None:
    """Test successful retrieval of skill instructions."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_instructions("test-skill")
    result = json.loads(result_json)

    assert result["skill_name"] == "test-skill"
    assert "instructions" in result
    assert "Follow these instructions" in result["instructions"]
    assert "available_scripts" in result
    assert "available_references" in result


def test_get_skill_instructions_not_found(mock_loader: MockSkillLoader) -> None:
    """Test retrieval of non-existent skill instructions."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_instructions("nonexistent")
    result = json.loads(result_json)

    assert "error" in result
    assert "not found" in result["error"].lower()
    assert "available_skills" in result


# --- Skill Reference Tool Tests ---


def test_get_skill_reference_skill_not_found(mock_loader: MockSkillLoader) -> None:
    """Test reference retrieval for non-existent skill."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_reference("nonexistent", "ref.md")
    result = json.loads(result_json)

    assert "error" in result
    assert "not found" in result["error"].lower()


def test_get_skill_reference_ref_not_found(mock_loader: MockSkillLoader) -> None:
    """Test reference retrieval for non-existent reference."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_reference("test-skill", "nonexistent.md")
    result = json.loads(result_json)

    assert "error" in result
    assert "not found" in result["error"].lower()
    assert "available_references" in result


def test_get_skill_reference_with_real_file(temp_skill_dir: Path) -> None:
    """Test reference retrieval with actual file."""
    loader = LocalSkills(str(temp_skill_dir))
    skills = Skills(loaders=[loader])

    result_json = skills._get_skill_reference("test-skill", "guide.md")
    result = json.loads(result_json)

    assert result["skill_name"] == "test-skill"
    assert result["reference_path"] == "guide.md"
    assert "content" in result
    assert "reference guide" in result["content"].lower()


def test_get_skill_reference_missing_path(mock_loader: MockSkillLoader) -> None:
    """Test reference retrieval returns a graceful error when reference_path is None.

    Models sometimes call the tool without a reference_path. The optional
    parameter lets that reach the graceful guard instead of raising a
    validate_call ValidationError at the tool boundary.
    """
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_reference("test-skill", None)
    result = json.loads(result_json)

    assert "error" in result
    assert "reference_path is required" in result["error"]
    assert result["available_references"] == ["guide.md", "api-docs.md"]


# --- Skill Script Tool Tests ---


def test_skill_script_read_skill_not_found(mock_loader: MockSkillLoader) -> None:
    """Test script read for non-existent skill."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_script("nonexistent", "script.py")
    result = json.loads(result_json)

    assert "error" in result
    assert "not found" in result["error"].lower()


def test_skill_script_read_script_not_found(mock_loader: MockSkillLoader) -> None:
    """Test script read for non-existent script."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_script("test-skill", "nonexistent.py")
    result = json.loads(result_json)

    assert "error" in result
    assert "not found" in result["error"].lower()
    assert "available_scripts" in result


def test_skill_script_read_with_real_file(temp_skill_dir: Path) -> None:
    """Test script read with actual file."""
    loader = LocalSkills(str(temp_skill_dir))
    skills = Skills(loaders=[loader])

    result_json = skills._get_skill_script("test-skill", "helper.py")
    result = json.loads(result_json)

    assert result["skill_name"] == "test-skill"
    assert result["script_path"] == "helper.py"
    assert "content" in result
    assert "Helper script" in result["content"]


def test_skill_script_read_missing_path(mock_loader: MockSkillLoader) -> None:
    """Test script read returns a graceful error when script_path is None.

    A skill with no scripts renders ``<scripts>none</scripts>`` in the system
    prompt, yet models occasionally still call get_skill_script without a
    script_path. The optional parameter lets that reach the graceful guard
    instead of raising a validate_call ValidationError at the tool boundary.
    """
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_script("test-skill", None)
    result = json.loads(result_json)

    assert "error" in result
    assert "script_path is required" in result["error"]
    assert result["available_scripts"] == ["helper.py", "runner.sh"]


# --- Content-Carrying Skill Tests ---


def test_content_skill_instructions(content_skill: Skill) -> None:
    """Test that a content-carrying skill serves instructions and its filename lists."""
    skills = Skills(loaders=[MockSkillLoader([content_skill])])
    result = json.loads(skills._get_skill_instructions("content-skill"))

    assert result["skill_name"] == "content-skill"
    assert "Follow these instructions" in result["instructions"]
    assert result["available_scripts"] == ["hello.py", "sibling.py"]
    assert result["available_references"] == ["guide.md"]


def test_content_skill_reference_served_from_contents(content_skill: Skill) -> None:
    """Test that a reference is served from reference_contents, with no filesystem access."""
    skills = Skills(loaders=[MockSkillLoader([content_skill])])
    result = json.loads(skills._get_skill_reference("content-skill", "guide.md"))

    assert result["skill_name"] == "content-skill"
    assert result["reference_path"] == "guide.md"
    assert result["content"] == "# Guide\n\nThis is a reference guide."


def test_content_skill_reference_not_declared(content_skill: Skill) -> None:
    """Test that an undeclared reference is rejected the same way as for a path-backed skill."""
    skills = Skills(loaders=[MockSkillLoader([content_skill])])
    result = json.loads(skills._get_skill_reference("content-skill", "nonexistent.md"))

    assert "error" in result
    assert "not found" in result["error"].lower()
    assert result["available_references"] == ["guide.md"]


def test_content_skill_script_read_served_from_contents(content_skill: Skill) -> None:
    """Test that a script read is served from script_contents, with no filesystem access."""
    skills = Skills(loaders=[MockSkillLoader([content_skill])])
    result = json.loads(skills._get_skill_script("content-skill", "hello.py"))

    assert result["skill_name"] == "content-skill"
    assert result["script_path"] == "hello.py"
    assert "hello from content" in result["content"]


def test_content_skill_script_execute(content_skill: Skill) -> None:
    """Test that a script from a content-carrying skill executes."""
    skills = Skills(loaders=[MockSkillLoader([content_skill])])
    result = json.loads(skills._get_skill_script("content-skill", "hello.py", execute=True))

    assert "error" not in result
    assert "hello from content" in result["stdout"]
    assert result["returncode"] == 0


def test_content_skill_script_execute_sees_sibling_files(content_skill: Skill) -> None:
    """Test that execution materializes the skill's other files alongside the one it runs."""
    content_skill.scripts.append("list_dir.py")
    assert content_skill.script_contents is not None
    content_skill.script_contents["list_dir.py"] = (
        '#!/usr/bin/env python3\nimport os\nprint(sorted(os.listdir("scripts")), sorted(os.listdir("references")))\n'
    )

    skills = Skills(loaders=[MockSkillLoader([content_skill])])
    result = json.loads(skills._get_skill_script("content-skill", "list_dir.py", execute=True))

    assert "error" not in result
    assert "sibling.py" in result["stdout"]
    assert "guide.md" in result["stdout"]


def test_content_skill_script_execute_cleans_up(content_skill: Skill) -> None:
    """Test that the temporary directory a script ran from does not outlive the call."""
    content_skill.scripts.append("print_cwd.py")
    assert content_skill.script_contents is not None
    content_skill.script_contents["print_cwd.py"] = "#!/usr/bin/env python3\nimport os\nprint(os.getcwd())\n"

    skills = Skills(loaders=[MockSkillLoader([content_skill])])
    result = json.loads(skills._get_skill_script("content-skill", "print_cwd.py", execute=True))

    assert "error" not in result
    assert not Path(result["stdout"].strip()).exists()


def test_content_skill_script_execute_timeout(content_skill: Skill) -> None:
    """Test that a content-carrying skill's script honours the timeout."""
    content_skill.scripts.append("sleep.py")
    assert content_skill.script_contents is not None
    content_skill.script_contents["sleep.py"] = "#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n"

    skills = Skills(loaders=[MockSkillLoader([content_skill])])
    result = json.loads(skills._get_skill_script("content-skill", "sleep.py", execute=True, timeout=1))

    assert "error" in result
    assert "timed out" in result["error"].lower()


# --- Path source_path Tests ---


def test_path_source_path_serves_reference_and_script(temp_skill_dir: Path) -> None:
    """Test that a skill whose source_path is a Path works through every tool that builds a path."""
    (temp_skill_dir / "scripts" / "path_runner.py").write_text('#!/usr/bin/env python3\nprint("ran from a Path")')
    skill = Skill(
        name="path-skill",
        description="Path-backed via a pathlib.Path",
        instructions="Instructions",
        source_path=temp_skill_dir,
        scripts=["path_runner.py"],
        references=["guide.md"],
    )
    skills = Skills(loaders=[MockSkillLoader([skill])])

    reference = json.loads(skills._get_skill_reference("path-skill", "guide.md"))
    assert "reference guide" in reference["content"].lower()

    read = json.loads(skills._get_skill_script("path-skill", "path_runner.py"))
    assert "ran from a Path" in read["content"]

    executed = json.loads(skills._get_skill_script("path-skill", "path_runner.py", execute=True))
    assert "error" not in executed
    assert "ran from a Path" in executed["stdout"]


def test_path_backed_and_content_carrying_skills_coexist(temp_skill_dir: Path, content_skill: Skill) -> None:
    """Test that a Path-backed skill and a content-carrying skill serve from one Skills instance."""
    path_skill = Skill(
        name="path-skill",
        description="Path-backed via a pathlib.Path",
        instructions="Instructions",
        source_path=temp_skill_dir,
        references=["guide.md"],
    )
    skills = Skills(loaders=[MockSkillLoader([path_skill]), MockSkillLoader([content_skill])])

    assert sorted(skills.get_skill_names()) == ["content-skill", "path-skill"]

    from_disk = json.loads(skills._get_skill_reference("path-skill", "guide.md"))
    from_contents = json.loads(skills._get_skill_reference("content-skill", "guide.md"))

    assert "reference guide" in from_disk["content"].lower()
    assert from_contents["content"] == "# Guide\n\nThis is a reference guide."


# --- Executor Tests ---


class StubExecutor(SkillExecutor):
    """An executor that records its call and returns a canned result instead of running anything."""

    def __init__(self) -> None:
        self.calls: List[dict] = []

    def run(
        self,
        script_path: Path,
        *,
        args: Optional[List[str]] = None,
        timeout: int = 30,
        cwd: Optional[Path] = None,
    ) -> ScriptResult:
        self.calls.append({"script_path": script_path, "args": args, "timeout": timeout, "cwd": cwd})
        return ScriptResult(stdout="stubbed", stderr="", returncode=0)


def test_executor_defaults_to_local(mock_loader: MockSkillLoader) -> None:
    """Test that Skills runs scripts locally unless given another executor."""
    skills = Skills(loaders=[mock_loader])

    assert isinstance(skills.executor, LocalSkillExecutor)


def test_executor_used_for_path_backed_skill(temp_skill_dir: Path) -> None:
    """Test that a path-backed skill's script execution is routed through the executor."""
    executor = StubExecutor()
    skills = Skills(loaders=[LocalSkills(str(temp_skill_dir))], executor=executor)

    result = json.loads(skills._get_skill_script("test-skill", "helper.py", execute=True, args=["x"], timeout=7))

    assert result["stdout"] == "stubbed"
    assert len(executor.calls) == 1
    assert executor.calls[0]["script_path"] == temp_skill_dir / "scripts" / "helper.py"
    assert executor.calls[0]["cwd"] == temp_skill_dir
    assert executor.calls[0]["args"] == ["x"]
    assert executor.calls[0]["timeout"] == 7


def test_executor_used_for_content_carrying_skill(content_skill: Skill) -> None:
    """Test that a content-carrying skill's script execution is routed through the executor."""
    executor = StubExecutor()
    skills = Skills(loaders=[MockSkillLoader([content_skill])], executor=executor)

    result = json.loads(skills._get_skill_script("content-skill", "hello.py", execute=True))

    assert result["stdout"] == "stubbed"
    assert len(executor.calls) == 1
    # The executor is handed the materialized file, inside the temporary skill directory.
    assert executor.calls[0]["script_path"].name == "hello.py"
    assert executor.calls[0]["script_path"].parent == executor.calls[0]["cwd"] / "scripts"


def test_executor_not_used_for_script_read(temp_skill_dir: Path) -> None:
    """Test that reading a script does not go through the executor."""
    executor = StubExecutor()
    skills = Skills(loaders=[LocalSkills(str(temp_skill_dir))], executor=executor)

    result = json.loads(skills._get_skill_script("test-skill", "helper.py"))

    assert "Helper script" in result["content"]
    assert executor.calls == []


# --- Error Handling Tests ---


def test_validation_error_propagates(invalid_skill_dir: Path) -> None:
    """Test that validation errors propagate from loaders during initialization."""
    loader = LocalSkills(str(invalid_skill_dir), validate=True)

    # With eager loading, validation error happens in __init__
    with pytest.raises(SkillValidationError):
        Skills(loaders=[loader])


def test_loader_error_logged_but_continues() -> None:
    """Test that loader errors are logged but don't stop loading."""

    class FailingLoader(SkillLoader):
        def load(self) -> List[Skill]:
            raise RuntimeError("Loader failed")

    working_skill = Skill(
        name="working",
        description="Works",
        instructions="Instructions",
        source_path="/path",
    )
    working_loader = MockSkillLoader([working_skill])
    failing_loader = FailingLoader()

    skills = Skills(loaders=[failing_loader, working_loader])
    # Should not raise, and should load skills from working loader
    all_skills = skills.get_all_skills()

    assert len(all_skills) == 1
    assert all_skills[0].name == "working"


# --- Path Traversal Prevention Tests ---


def test_get_skill_reference_path_traversal_blocked(mock_loader: MockSkillLoader) -> None:
    """Test that path traversal attempts are blocked for references."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_reference("test-skill", "../../../etc/passwd")
    result = json.loads(result_json)

    assert "error" in result
    # Should be caught by the "not in skill.references" check first
    assert "not found" in result["error"].lower()


def test_skill_script_path_traversal_blocked(mock_loader: MockSkillLoader) -> None:
    """Test that path traversal attempts are blocked for scripts."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_script("test-skill", "../../../etc/passwd")
    result = json.loads(result_json)

    assert "error" in result
    # Should be caught by the "not in skill.scripts" check first
    assert "not found" in result["error"].lower()


def test_is_safe_path_allows_valid_paths(tmp_path: Path) -> None:
    """Test that is_safe_path allows valid paths."""
    from agno.skills.utils import is_safe_path

    # Create real directories for testing
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    subdir = base_dir / "subdir"
    subdir.mkdir()

    assert is_safe_path(base_dir, "file.txt") is True
    assert is_safe_path(base_dir, "subdir/file.txt") is True


def test_is_safe_path_blocks_traversal(tmp_path: Path) -> None:
    """Test that is_safe_path blocks path traversal attempts."""
    from agno.skills.utils import is_safe_path

    base_dir = tmp_path / "base"
    base_dir.mkdir()

    assert is_safe_path(base_dir, "../file.txt") is False
    assert is_safe_path(base_dir, "../../file.txt") is False
    assert is_safe_path(base_dir, "../../../etc/passwd") is False
    assert is_safe_path(base_dir, "subdir/../../file.txt") is False


def test_skill_script_execute_skill_not_found(mock_loader: MockSkillLoader) -> None:
    """Test script execution for non-existent skill."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_script("nonexistent", "script.py", execute=True)
    result = json.loads(result_json)

    assert "error" in result
    assert "not found" in result["error"].lower()
    assert "available_skills" in result


def test_skill_script_execute_script_not_found(mock_loader: MockSkillLoader) -> None:
    """Test script execution for non-existent script."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_script("test-skill", "nonexistent.py", execute=True)
    result = json.loads(result_json)

    assert "error" in result
    assert "not found" in result["error"].lower()
    assert "available_scripts" in result


def test_skill_script_execute_success(temp_skill_dir: Path) -> None:
    """Test successful script execution."""
    # Create a simple test script with shebang (chmod handled automatically)
    scripts_dir = temp_skill_dir / "scripts"
    test_script = scripts_dir / "test_runner.py"
    test_script.write_text('#!/usr/bin/env python3\nprint("Hello from script")')

    loader = LocalSkills(str(temp_skill_dir))
    skills = Skills(loaders=[loader])

    result_json = skills._get_skill_script("test-skill", "test_runner.py", execute=True)
    result = json.loads(result_json)

    assert "error" not in result
    assert result["skill_name"] == "test-skill"
    assert result["script_path"] == "test_runner.py"
    assert "Hello from script" in result["stdout"]
    assert result["returncode"] == 0


def test_skill_script_execute_with_args(temp_skill_dir: Path) -> None:
    """Test script execution with arguments."""
    scripts_dir = temp_skill_dir / "scripts"
    test_script = scripts_dir / "echo_args.py"
    test_script.write_text('#!/usr/bin/env python3\nimport sys; print(" ".join(sys.argv[1:]))')

    loader = LocalSkills(str(temp_skill_dir))
    skills = Skills(loaders=[loader])

    result_json = skills._get_skill_script("test-skill", "echo_args.py", execute=True, args=["arg1", "arg2"])
    result = json.loads(result_json)

    assert "error" not in result
    assert "arg1 arg2" in result["stdout"]


def test_skill_script_execute_captures_stderr(temp_skill_dir: Path) -> None:
    """Test that stderr is captured."""
    scripts_dir = temp_skill_dir / "scripts"
    test_script = scripts_dir / "stderr_test.py"
    test_script.write_text('#!/usr/bin/env python3\nimport sys; print("error message", file=sys.stderr)')

    loader = LocalSkills(str(temp_skill_dir))
    skills = Skills(loaders=[loader])

    result_json = skills._get_skill_script("test-skill", "stderr_test.py", execute=True)
    result = json.loads(result_json)

    assert "error" not in result
    assert "error message" in result["stderr"]


def test_skill_script_execute_nonzero_exit(temp_skill_dir: Path) -> None:
    """Test script with non-zero exit code."""
    scripts_dir = temp_skill_dir / "scripts"
    test_script = scripts_dir / "exit_code.py"
    test_script.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(42)")

    loader = LocalSkills(str(temp_skill_dir))
    skills = Skills(loaders=[loader])

    result_json = skills._get_skill_script("test-skill", "exit_code.py", execute=True)
    result = json.loads(result_json)

    assert "error" not in result
    assert result["returncode"] == 42


def test_skill_script_execute_path_traversal_blocked(mock_loader: MockSkillLoader) -> None:
    """Test that path traversal attempts are blocked for script execution."""
    skills = Skills(loaders=[mock_loader])
    result_json = skills._get_skill_script("test-skill", "../../../etc/passwd", execute=True)
    result = json.loads(result_json)

    assert "error" in result
    assert "not found" in result["error"].lower()
