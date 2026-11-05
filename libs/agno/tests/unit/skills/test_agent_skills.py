"""Unit tests for Skills orchestrator class."""

import asyncio
import copy
import json
import threading
from pathlib import Path
from typing import Callable, ClassVar, Dict, List, Optional, Set

import pytest

from agno.run.base import RunContext
from agno.skills.agent_skills import Skills
from agno.skills.errors import SkillValidationError
from agno.skills.executor import LocalSkillExecutor, SkillExecutor
from agno.skills.loaders.base import SkillLoader
from agno.skills.loaders.local import LocalSkills
from agno.skills.skill import Skill
from agno.skills.utils import ScriptResult
from agno.tools.function import Function, FunctionCall

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


# ============================================================================
# OWNER-SCOPED VIEWS
# ============================================================================


class OwnerScopedLoader(SkillLoader):
    """A per-request, owner-scoped loader serving the shared skills plus one user's own."""

    refresh_per_request: ClassVar[bool] = True
    owner_scoped: ClassVar[bool] = True

    def __init__(self, owned: Dict[Optional[str], List[Skill]]) -> None:
        self.owned = owned

    def load(self, *, user_id: Optional[str] = None) -> List[Skill]:
        return list(self.owned.get(None, [])) + (list(self.owned.get(user_id, [])) if user_id else [])


def _owner_scoped_skills(sample_skill: Skill, minimal_skill: Skill, content_skill: Skill) -> Skills:
    """test-skill is shared, minimal-skill is alice's, content-skill is bob's."""
    return Skills(loaders=[OwnerScopedLoader({None: [sample_skill], "alice": [minimal_skill], "bob": [content_skill]})])


def _call_tool(skills: Skills, name: str, user_id: Optional[str], **arguments: object) -> dict:
    """Run a skill tool the way the runtime does: the run context is injected, never an argument."""
    function = next(f for f in skills.get_tools() if f.name == name)
    function._run_context = RunContext(run_id="run", session_id="session", user_id=user_id)
    call = FunctionCall(function=function, arguments=arguments)
    assert call.execute().status == "success"
    return json.loads(call.result)


def test_owner_scoped_views_do_not_replace_each_other(
    sample_skill: Skill, minimal_skill: Skill, content_skill: Skill
) -> None:
    """Alice's prompt, then bob's on the same object, then alice's tool call: each user reads
    the set their own prompt advertised, and nobody reads another user's skill by name."""
    skills = _owner_scoped_skills(sample_skill, minimal_skill, content_skill)

    for _ in range(2):
        alice_prompt = skills.get_system_prompt_snippet(user_id="alice")
        bob_prompt = skills.get_system_prompt_snippet(user_id="bob")
        assert "minimal-skill" in alice_prompt and "content-skill" not in alice_prompt
        assert "content-skill" in bob_prompt and "minimal-skill" not in bob_prompt

        alice_call = _call_tool(skills, "get_skill_instructions", "alice", skill_name="minimal-skill")
        assert alice_call["skill_name"] == "minimal-skill"
        bob_call = _call_tool(skills, "get_skill_instructions", "bob", skill_name="minimal-skill")
        assert "not found" in bob_call["error"]
        assert "content-skill" in bob_call["available_skills"] and "minimal-skill" not in bob_call["available_skills"]

        # No user: the shared mapping, exactly as before owner scoping existed.
        no_user_prompt = skills.get_system_prompt_snippet()
        assert "test-skill" in no_user_prompt and "minimal-skill" not in no_user_prompt
        assert "not found" in _call_tool(skills, "get_skill_instructions", None, skill_name="minimal-skill")["error"]
        assert skills.get_skill_names() == ["test-skill"]


async def test_owner_scoped_views_do_not_replace_each_other_async(
    sample_skill: Skill, minimal_skill: Skill, content_skill: Skill
) -> None:
    skills = _owner_scoped_skills(sample_skill, minimal_skill, content_skill)

    for _ in range(2):
        alice_prompt = await skills.aget_system_prompt_snippet(user_id="alice")
        bob_prompt = await skills.aget_system_prompt_snippet(user_id="bob")
        assert "minimal-skill" in alice_prompt and "content-skill" not in alice_prompt
        assert "content-skill" in bob_prompt and "minimal-skill" not in bob_prompt

        assert (
            _call_tool(skills, "get_skill_instructions", "alice", skill_name="minimal-skill")["skill_name"]
            == "minimal-skill"
        )
        assert "not found" in _call_tool(skills, "get_skill_instructions", "bob", skill_name="minimal-skill")["error"]
        assert "minimal-skill" not in await skills.aget_system_prompt_snippet()


def test_a_tool_call_without_a_prompt_resolves_the_users_view(
    sample_skill: Skill, minimal_skill: Skill, content_skill: Skill, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resumed run or an evicted entry reaches a tool with no view for its user: the tool
    resolves the user's view rather than answering from the shared mapping alone. Views are
    bounded; the oldest user's is dropped and comes back on that user's next request."""
    monkeypatch.setattr("agno.skills.agent_skills._USER_VIEWS_KEPT", 2)
    skills = _owner_scoped_skills(sample_skill, minimal_skill, content_skill)

    for _ in range(2):
        assert (
            _call_tool(skills, "get_skill_instructions", "alice", skill_name="minimal-skill")["skill_name"]
            == "minimal-skill"
        )

        skills.get_system_prompt_snippet(user_id="bob")
        skills.get_system_prompt_snippet(user_id="carol")
        assert list(skills._user_skills) == ["bob", "carol"]
        assert (
            _call_tool(skills, "get_skill_instructions", "alice", skill_name="minimal-skill")["skill_name"]
            == "minimal-skill"
        )
        assert list(skills._user_skills) == ["carol", "alice"]


# The three tools' schemas as main publishes them: the run context a tool reads is injected
# by the runtime, so nothing about it may reach the model.
_SKILL_TOOL_SCHEMAS = {
    "get_skill_instructions": {
        "properties": {
            "skill_name": {"description": "The name of the skill to get instructions for.", "type": "string"}
        },
        "required": ["skill_name"],
        "type": "object",
    },
    "get_skill_reference": {
        "properties": {
            "reference_path": {"description": "The filename of the reference document.", "type": "string"},
            "skill_name": {"description": "The name of the skill.", "type": "string"},
        },
        "required": ["skill_name"],
        "type": "object",
    },
    "get_skill_script": {
        "properties": {
            "args": {
                "description": "Optional list of arguments to pass to the script (only used if execute=True).",
                "items": {"type": "string"},
                "type": "array",
            },
            "execute": {
                "description": "If True, execute the script. If False (default), return content.",
                "type": "boolean",
            },
            "script_path": {"description": "The filename of the script.", "type": "string"},
            "skill_name": {"description": "The name of the skill.", "type": "string"},
            "timeout": {
                "description": "Maximum execution time in seconds (default: 30, only used if execute=True).",
                "type": "integer",
            },
        },
        "required": ["skill_name"],
        "type": "object",
    },
}


def test_skill_tool_schemas_are_unchanged(mock_loader: MockSkillLoader) -> None:
    tools = Skills(loaders=[mock_loader]).get_tools()
    for tool in tools:
        tool.process_entrypoint()
    assert {tool.name: tool.parameters for tool in tools} == _SKILL_TOOL_SCHEMAS


# ============================================================================
# CONCURRENT REFRESHES
# ============================================================================


def _row(name: str) -> Skill:
    return Skill(name=name, description="d", instructions="i", source_path=f"/path/to/{name}")


class ParkedLoader(SkillLoader):
    """Owner-scoped and per request; alice's async read waits to be released, every other read returns at once."""

    refresh_per_request: ClassVar[bool] = True
    owner_scoped: ClassVar[bool] = True

    def __init__(self) -> None:
        self.release = asyncio.Event()

    def load(self, *, user_id: Optional[str] = None) -> List[Skill]:
        return [_row(f"{user_id or 'shared'}-skill")]

    async def aload(self, *, user_id: Optional[str] = None) -> List[Skill]:
        if user_id == "alice":
            await self.release.wait()
        return [_row(f"{user_id or 'shared'}-skill")]


async def test_one_users_async_refresh_does_not_wait_for_anothers() -> None:
    """Every run of an agent shares one Skills object under AgentOS: a user's prompt build
    parked on its database read must not hold up another user's prompt build."""
    loader = ParkedLoader()
    skills = Skills(loaders=[loader])

    alice = asyncio.create_task(skills.aget_system_prompt_snippet(user_id="alice"))
    await asyncio.sleep(0)  # alice is parked on her read
    bob_prompt = await asyncio.wait_for(skills.aget_system_prompt_snippet(user_id="bob"), timeout=1)
    assert "bob-skill" in bob_prompt

    loader.release.set()
    assert "alice-skill" in await alice
    assert skills.get_skill_names() == ["shared-skill"]


class UnloadedLoader(SkillLoader):
    """Owner-scoped and per request, never loaded eagerly (an async database). Its first
    no-user async read can park until released, and one task's no-user read can be failed."""

    refresh_per_request: ClassVar[bool] = True
    owner_scoped: ClassVar[bool] = True

    def __init__(self, name: str, *, parks: bool = False) -> None:
        self.name = name
        self.parks = parks
        self.release = asyncio.Event()
        self.fail_for_task: Optional["asyncio.Task[None]"] = None

    def load(self, *, user_id: Optional[str] = None) -> List[Skill]:
        raise RuntimeError("async database: the sync read is unavailable")

    async def aload(self, *, user_id: Optional[str] = None) -> List[Skill]:
        if user_id is None and self.parks:
            self.parks = False
            await self.release.wait()
        if user_id is None and asyncio.current_task() is self.fail_for_task:
            raise RuntimeError("transient failure")
        return [_row(f"{self.name}-{user_id or 'shared'}")]


async def test_a_refresh_that_commits_last_keeps_a_siblings_shared_rows_async() -> None:
    """A no-user refresh parked on one read resumes after a user's refresh has filled the
    shared rows of both loaders; failing its own second read, it must build on what the
    sibling committed rather than commit the empty snapshot it started from."""
    first, second = UnloadedLoader("first", parks=True), UnloadedLoader("second")
    skills = Skills(loaders=[first, second])
    assert skills.get_skill_names() == []

    parked = asyncio.create_task(skills._arefresh_loaders())
    await asyncio.sleep(0)
    second.fail_for_task = parked
    await asyncio.wait_for(skills._arefresh_loaders(user_id="alice"), timeout=1)
    assert skills.get_skill_names() == ["first-shared", "second-shared"]

    first.release.set()
    await parked
    assert skills.get_skill_names() == ["first-shared", "second-shared"]
    assert "first-alice" in skills.get_system_prompt_snippet(user_id="alice")


class NestingLoader(SkillLoader):
    """The sync twin of UnloadedLoader: never loaded eagerly, and its first no-user read runs
    a sibling refresh on the same object (a thread interleaving, made deterministic)."""

    refresh_per_request: ClassVar[bool] = True
    owner_scoped: ClassVar[bool] = True

    def __init__(self, name: str) -> None:
        self.name = name
        self.loaded_eagerly = False
        self.nested: Optional[Callable[[], None]] = None
        self.fail_next_no_user_read = False

    def load(self, *, user_id: Optional[str] = None) -> List[Skill]:
        if not self.loaded_eagerly:
            self.loaded_eagerly = True
            raise RuntimeError("async database: the sync read is unavailable")
        if user_id is None and self.nested is not None:
            nested, self.nested = self.nested, None
            nested()
        if user_id is None and self.fail_next_no_user_read:
            self.fail_next_no_user_read = False
            raise RuntimeError("transient failure")
        return [_row(f"{self.name}-{user_id or 'shared'}")]


def test_a_refresh_that_commits_last_keeps_a_siblings_shared_rows() -> None:
    """Sync twin: a sibling refresh commits in the middle of a no-user refresh's reads, and the
    no-user refresh then fails its own second read; it must keep the sibling's shared rows."""
    first, second = NestingLoader("first"), NestingLoader("second")
    skills = Skills(loaders=[first, second])
    assert skills.get_skill_names() == []

    def sibling() -> None:
        skills._refresh_loaders(user_id="alice")
        assert skills.get_skill_names() == ["first-shared", "second-shared"]
        second.fail_next_no_user_read = True

    first.nested = sibling
    skills._refresh_loaders()
    assert skills.get_skill_names() == ["first-shared", "second-shared"]
    assert "first-alice" in skills.get_system_prompt_snippet(user_id="alice")


class StaleReadLoader(SkillLoader):
    """Owner-scoped and per request; the first async read keeps the rows it saw and parks until
    released, so it commits after a later read that saw newer rows."""

    refresh_per_request: ClassVar[bool] = True
    owner_scoped: ClassVar[bool] = True

    def __init__(self) -> None:
        self.rows = [_row("old-skill")]
        self.release = asyncio.Event()
        self.parked = False

    def load(self, *, user_id: Optional[str] = None) -> List[Skill]:
        return list(self.rows)

    async def aload(self, *, user_id: Optional[str] = None) -> List[Skill]:
        rows = list(self.rows)
        if not self.parked:
            self.parked = True
            await self.release.wait()
        return rows


async def test_a_views_older_refresh_does_not_write_over_a_newer_one() -> None:
    """Same view, two overlapping async refreshes: the later one is not held back behind the
    older one's read, another view's refresh runs alongside, and the older one's commit is
    dropped, so the view keeps what the later prompt advertised."""
    loader = StaleReadLoader()
    skills = Skills(loaders=[loader])

    for _ in range(2):
        loader.rows, loader.parked, loader.release = [_row("old-skill")], False, asyncio.Event()
        older = asyncio.create_task(skills.aget_system_prompt_snippet(user_id="alice"))
        await asyncio.sleep(0)  # the older refresh has read old-skill and is parked
        loader.rows = [_row("new-skill")]
        assert "new-skill" in await asyncio.wait_for(skills.aget_system_prompt_snippet(user_id="alice"), timeout=1)
        assert "new-skill" in await asyncio.wait_for(skills.aget_system_prompt_snippet(user_id="bob"), timeout=1)

        loader.release.set()
        await older
        assert list(skills._view_for("alice")) == ["new-skill"]
        assert skills.get_skill_names() == ["old-skill"]


def test_refresh_bookkeeping_does_not_grow_with_users(sample_skill: Skill) -> None:
    """A loader that never refreshes records nothing, a failed read commits nothing, and a
    committed refresh is forgotten with its view, so nothing grows per user id."""
    from agno.skills.agent_skills import _USER_VIEWS_KEPT

    plain = Skills(loaders=[MockSkillLoader([sample_skill])])
    for n in range(300):
        plain.get_system_prompt_snippet(user_id=f"user-{n}")
    assert plain._committed_refreshes == {}

    failing = RefreshingLoader([sample_skill])
    failing.fail = True
    down = Skills(loaders=[failing])
    for n in range(300):
        down.get_system_prompt_snippet(user_id=f"user-{n}")
    assert down._committed_refreshes == {}

    up = Skills(loaders=[RefreshingLoader([sample_skill])])
    for n in range(300):
        up.get_system_prompt_snippet(user_id=f"user-{n}")
    assert set(up._committed_refreshes) == set(up._user_skills)
    assert len(up._user_skills) == _USER_VIEWS_KEPT


async def test_async_refresh_bookkeeping_does_not_grow_with_users(sample_skill: Skill) -> None:
    """Async twin of test_refresh_bookkeeping_does_not_grow_with_users."""
    from agno.skills.agent_skills import _USER_VIEWS_KEPT

    plain = Skills(loaders=[MockSkillLoader([sample_skill])])
    for n in range(300):
        await plain.aget_system_prompt_snippet(user_id=f"user-{n}")
    assert plain._committed_refreshes == {}

    failing = AsyncRefreshingLoader([sample_skill])
    failing.fail = True
    down = Skills(loaders=[failing])
    for n in range(300):
        await down.aget_system_prompt_snippet(user_id=f"user-{n}")
    assert down._committed_refreshes == {}

    up = Skills(loaders=[AsyncRefreshingLoader([sample_skill])])
    for n in range(300):
        await up.aget_system_prompt_snippet(user_id=f"user-{n}")
    assert set(up._committed_refreshes) == set(up._user_skills)
    assert len(up._user_skills) == _USER_VIEWS_KEPT


# ============================================================================
# SHARED STATE ACROSS VIEWS
# ============================================================================


class ParkableLoader(OwnerScopedLoader):
    """An OwnerScopedLoader whose reads keep the rows they saw when they started: one view's
    next sync read can be parked on a threading event and its next async read on an asyncio
    event, and a view's reads can be failed."""

    def __init__(self, owned: Dict[Optional[str], List[Skill]]) -> None:
        super().__init__(owned)
        self.park_sync: Dict[Optional[str], threading.Event] = {}
        self.park_async: Dict[Optional[str], asyncio.Event] = {}
        self.parked = threading.Event()
        self.failing: Set[Optional[str]] = set()

    def _rows(self, user_id: Optional[str]) -> List[Skill]:
        if user_id in self.failing:
            raise RuntimeError("database down")
        return super().load(user_id=user_id)

    def load(self, *, user_id: Optional[str] = None) -> List[Skill]:
        rows = self._rows(user_id)
        gate = self.park_sync.pop(user_id, None)
        if gate is not None:
            self.parked.set()
            gate.wait()
        return rows

    async def aload(self, *, user_id: Optional[str] = None) -> List[Skill]:
        rows = self._rows(user_id)
        gate = self.park_async.pop(user_id, None)
        if gate is not None:
            self.parked.set()
            await gate.wait()
        return rows


def _parkable(sample_skill: Skill, minimal_skill: Skill, content_skill: Skill) -> ParkableLoader:
    """The _owner_scoped_skills map, parkable."""
    return ParkableLoader({None: [sample_skill], "alice": [minimal_skill], "bob": [content_skill]})


def _cached_names(skills: Skills) -> Set[str]:
    return {skill.name for rows in skills._loader_results.values() for skill in rows}


def _in_thread(skills: Skills, user_id: Optional[str]) -> threading.Thread:
    """A worker thread building the prompt for one view, started and joined by the test."""
    return threading.Thread(target=skills.get_system_prompt_snippet, kwargs={"user_id": user_id}, daemon=True)


def test_a_users_refresh_keeps_owned_rows_out_of_the_shared_state(
    sample_skill: Skill, minimal_skill: Skill, content_skill: Skill
) -> None:
    """Owned rows reach only their user's view: never the per-loader cache, the shared mapping,
    another user's view or a later anonymous prompt."""
    skills = Skills(loaders=[_parkable(sample_skill, minimal_skill, content_skill)])
    for _ in range(2):
        skills.get_system_prompt_snippet(user_id="alice")
        skills.get_system_prompt_snippet(user_id="bob")
        assert _cached_names(skills) == {"test-skill"}
        assert skills.get_skill_names() == ["test-skill"]
        assert list(skills._view_for("alice")) == ["test-skill", "minimal-skill"]
        assert list(skills._view_for("bob")) == ["test-skill", "content-skill"]
        assert "minimal-skill" not in skills.get_system_prompt_snippet()
        assert _cached_names(skills) == {"test-skill"}


async def test_a_users_refresh_keeps_owned_rows_out_of_the_shared_state_async(
    sample_skill: Skill, minimal_skill: Skill, content_skill: Skill
) -> None:
    skills = Skills(loaders=[_parkable(sample_skill, minimal_skill, content_skill)])
    for _ in range(2):
        await skills.aget_system_prompt_snippet(user_id="alice")
        await skills.aget_system_prompt_snippet(user_id="bob")
        assert _cached_names(skills) == {"test-skill"}
        assert skills.get_skill_names() == ["test-skill"]
        assert list(skills._view_for("alice")) == ["test-skill", "minimal-skill"]
        assert list(skills._view_for("bob")) == ["test-skill", "content-skill"]
        assert "minimal-skill" not in await skills.aget_system_prompt_snippet()
        assert _cached_names(skills) == {"test-skill"}


def test_two_users_sync_refreshes_interleave_without_mixing_views(
    sample_skill: Skill, minimal_skill: Skill, content_skill: Skill
) -> None:
    """Sync twin of the parked-user case: alice's read parked on a worker thread holds up neither
    bob's refresh on another thread nor the anonymous one, and each view ends with its own rows."""
    loader = _parkable(sample_skill, minimal_skill, content_skill)
    skills = Skills(loaders=[loader])

    for _ in range(2):
        gate = loader.park_sync["alice"] = threading.Event()
        loader.parked = threading.Event()
        alice = _in_thread(skills, "alice")
        alice.start()
        try:
            assert loader.parked.wait(1)
            bob = _in_thread(skills, "bob")
            bob.start()
            bob.join(1)
            assert not bob.is_alive()
            assert "test-skill" in skills.get_system_prompt_snippet()
            assert list(skills._view_for("bob")) == ["test-skill", "content-skill"]
        finally:
            gate.set()
        alice.join(1)
        assert not alice.is_alive()
        assert list(skills._view_for("alice")) == ["test-skill", "minimal-skill"]
        assert list(skills._view_for("bob")) == ["test-skill", "content-skill"]
        assert skills.get_skill_names() == ["test-skill"]
        assert _cached_names(skills) == {"test-skill"}


def test_a_siblings_shared_rows_survive_a_commit_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """A no-user refresh assembles its results, then stores them. A user's refresh on another
    thread tries to commit in between (a thread interleaving, made deterministic by starting it
    from inside the merge) and fills the shared rows of a loader the no-user refresh failed to
    read; those rows must survive the no-user store, whichever commit lands first."""
    first, second = NestingLoader("first"), NestingLoader("second")
    skills = Skills(loaders=[first, second])
    assert skills.get_skill_names() == []
    second.fail_next_no_user_read = True

    sibling = threading.Thread(target=skills._refresh_loaders, kwargs={"user_id": "alice"}, daemon=True)
    merge = skills._merge_loader_results

    def merge_with_a_sibling_landing(results: Dict[int, List[Skill]]) -> Dict[str, Skill]:
        monkeypatch.setattr(skills, "_merge_loader_results", merge)
        sibling.start()
        sibling.join(0.1)  # finishes at once unless the commit in progress keeps it out
        return merge(results)

    monkeypatch.setattr(skills, "_merge_loader_results", merge_with_a_sibling_landing)
    skills._refresh_loaders()
    sibling.join(1)
    assert not sibling.is_alive()
    assert skills.get_skill_names() == ["first-shared", "second-shared"]
    assert set(skills._loader_results) == {0, 1}
    assert "first-alice" in skills.get_system_prompt_snippet(user_id="alice")


def test_a_failed_user_refresh_leaves_every_other_view_alone(
    sample_skill: Skill, minimal_skill: Skill, content_skill: Skill
) -> None:
    """Alice's read fails: her previous view still serves her prompt, and bob's view, the
    shared mapping and the per-loader cache are untouched."""
    loader = _parkable(sample_skill, minimal_skill, content_skill)
    skills = Skills(loaders=[loader])

    for _ in range(2):
        skills.get_system_prompt_snippet(user_id="alice")
        skills.get_system_prompt_snippet(user_id="bob")
        loader.failing.add("alice")
        assert "minimal-skill" in skills.get_system_prompt_snippet(user_id="alice")
        assert list(skills._view_for("bob")) == ["test-skill", "content-skill"]
        assert skills.get_skill_names() == ["test-skill"]
        assert _cached_names(skills) == {"test-skill"}
        loader.failing.clear()


async def test_a_failed_user_refresh_leaves_every_other_view_alone_async(
    sample_skill: Skill, minimal_skill: Skill, content_skill: Skill
) -> None:
    loader = _parkable(sample_skill, minimal_skill, content_skill)
    skills = Skills(loaders=[loader])

    for _ in range(2):
        await skills.aget_system_prompt_snippet(user_id="alice")
        await skills.aget_system_prompt_snippet(user_id="bob")
        loader.failing.add("alice")
        assert "minimal-skill" in await skills.aget_system_prompt_snippet(user_id="alice")
        assert list(skills._view_for("bob")) == ["test-skill", "content-skill"]
        assert skills.get_skill_names() == ["test-skill"]
        assert _cached_names(skills) == {"test-skill"}
        loader.failing.clear()


async def test_evicting_a_view_during_its_own_refresh_keeps_the_refresh_result(
    sample_skill: Skill, minimal_skill: Skill, content_skill: Skill, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alice's refresh is in flight when two other users push her view out of the bounded dict:
    her refresh still lands as the newest view, the others' views are untouched, and the bound holds."""
    monkeypatch.setattr("agno.skills.agent_skills._USER_VIEWS_KEPT", 2)
    loader = _parkable(sample_skill, minimal_skill, content_skill)
    loader.owned["carol"] = [_row("carol-skill")]
    skills = Skills(loaders=[loader])

    for _ in range(2):
        await skills.aget_system_prompt_snippet(user_id="alice")
        gate = loader.park_async["alice"] = asyncio.Event()
        parked = asyncio.create_task(skills.aget_system_prompt_snippet(user_id="alice"))
        await asyncio.sleep(0)
        try:
            await skills.aget_system_prompt_snippet(user_id="bob")
            await skills.aget_system_prompt_snippet(user_id="carol")
            assert list(skills._user_skills) == ["bob", "carol"]
        finally:
            gate.set()
        assert "minimal-skill" in await parked
        assert list(skills._user_skills) == ["carol", "alice"]
        assert list(skills._view_for("carol")) == ["test-skill", "carol-skill"]
        assert list(skills._view_for("alice")) == ["test-skill", "minimal-skill"]
        assert skills.get_skill_names() == ["test-skill"]


# ============================================================================
# SYNC AND ASYNC REFRESHES OF ONE VIEW
# ============================================================================


async def test_a_sync_and_an_async_refresh_of_one_view_cannot_land_out_of_order() -> None:
    """A sync refresh on a worker thread and an async one on the loop, for the same view: the
    one that started earlier and read older rows must not write over the later one's newer
    rows, whichever path each took, for the shared view and for a user's."""
    stale = []
    for user_id in (None, "alice"):
        loader = ParkableLoader({None: [_row("old-skill")]})
        skills = Skills(loaders=[loader])
        for older_path in ("sync", "async", "sync", "async"):
            loader.owned[None], loader.parked = [_row("old-skill")], threading.Event()
            # Each gate is also released on a timer, so a lock held across a read would fail here, not hang.
            if older_path == "sync":
                gate = loader.park_sync[user_id] = threading.Event()
                threading.Timer(2, gate.set).start()
                older = asyncio.create_task(asyncio.to_thread(skills.get_system_prompt_snippet, user_id=user_id))
                assert await asyncio.to_thread(loader.parked.wait, 1)
                loader.owned[None] = [_row("new-skill")]
                assert "new-skill" in await skills.aget_system_prompt_snippet(user_id=user_id)
                gate.set()
            else:
                agate = loader.park_async[user_id] = asyncio.Event()
                asyncio.get_running_loop().call_later(2, agate.set)
                older = asyncio.create_task(skills.aget_system_prompt_snippet(user_id=user_id))
                await asyncio.sleep(0)
                assert loader.parked.is_set()
                loader.owned[None] = [_row("new-skill")]
                assert "new-skill" in await asyncio.to_thread(skills.get_system_prompt_snippet, user_id=user_id)
                agate.set()
            await older
            if list(skills._view_for(user_id)) != ["new-skill"]:
                stale.append((user_id, older_path))
    assert stale == []


def test_two_sync_refreshes_of_one_view_keep_the_newer_rows() -> None:
    """Two worker threads refresh the same view: the later one is not held back behind the
    older one's read, and the older one's commit is dropped, so the view holds the newer rows."""
    loader = ParkableLoader({None: [_row("old-skill")]})
    skills = Skills(loaders=[loader])

    for _ in range(2):
        loader.owned[None], loader.parked = [_row("old-skill")], threading.Event()
        gate = loader.park_sync["alice"] = threading.Event()
        older = _in_thread(skills, "alice")
        older.start()
        try:
            assert loader.parked.wait(1)
            loader.owned[None] = [_row("new-skill")]
            newer = _in_thread(skills, "alice")
            newer.start()
            newer.join(1)
            assert not newer.is_alive()
        finally:
            gate.set()
        older.join(1)
        assert not older.is_alive()
        assert list(skills._view_for("alice")) == ["new-skill"]


async def test_a_sync_refresh_on_the_loop_does_not_wait_behind_a_workers_read() -> None:
    """A skill tool with an async tool hook runs on the loop thread, and refreshes its user's
    view there when none exists. A worker thread's refresh of the same view, parked on its
    database read, must not hold the loop: a heartbeat keeps ticking while the worker's read
    is awaited, and the view ends with the newer rows."""
    loader = ParkableLoader({None: [_row("old-skill")]})
    skills = Skills(loaders=[loader])
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    try:
        for _ in range(2):
            loader.owned[None], loader.parked = [_row("old-skill")], threading.Event()
            gate = loader.park_sync["alice"] = threading.Event()
            worker = asyncio.create_task(asyncio.to_thread(skills.get_system_prompt_snippet, user_id="alice"))
            try:
                assert await asyncio.to_thread(loader.parked.wait, 1)
                loader.owned[None] = [_row("new-skill")]
                threading.Timer(0.3, gate.set).start()
                ticks = 0
                skills.get_system_prompt_snippet(user_id="alice")  # on the loop thread, as such a tool call does
                await worker
            finally:
                gate.set()
            assert ticks >= 5, ticks
            assert list(skills._view_for("alice")) == ["new-skill"]
    finally:
        beat.cancel()


def test_a_copied_skills_object_gets_a_lock_of_its_own(sample_skill: Skill, minimal_skill: Skill) -> None:
    """A lock cannot be copied, so a deep copy of a Skills object, after refreshes on either
    path, gets its own lock and its own bookkeeping; the two then refresh apart."""
    loader = RefreshingLoader([sample_skill])
    skills = Skills(loaders=[loader])
    skills.get_system_prompt_snippet(user_id="alice")

    for _ in range(2):
        copied = copy.deepcopy(skills)
        assert copied._refresh_lock is not skills._refresh_lock
        assert list(copied._view_for("alice")) == ["test-skill"]
        copied.loaders[0]._skills = [minimal_skill]
        assert "minimal-skill" in copied.get_system_prompt_snippet(user_id="alice")
        assert list(skills._view_for("alice")) == ["test-skill"]
        assert "test-skill" in skills.get_system_prompt_snippet(user_id="alice")
