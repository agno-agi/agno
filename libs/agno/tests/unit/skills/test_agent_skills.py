"""Unit tests for Skills orchestrator class."""

import json
from pathlib import Path
from typing import List

import pytest

from agno.skills.agent_skills import Skills
from agno.skills.errors import SkillValidationError
from agno.skills.loaders.base import SkillLoader
from agno.skills.loaders.local import LocalSkills
from agno.skills.skill import Skill
from agno.tools.function import Function

from .conftest import MockSkillLoader

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
    """Test that reload() clears existing skills and reloads."""
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

    # Reload should clear and reload
    skills.reload()
    assert "new-skill" in skills._skills
    assert "test-skill" not in skills._skills


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


def test_get_system_prompt_shows_none_when_no_references(minimal_skill: Skill) -> None:
    """Test that system prompt shows <references>none</references> when skill has no references."""
    loader = MockSkillLoader([minimal_skill])
    skills = Skills(loaders=[loader])
    snippet = skills.get_system_prompt_snippet()

    assert "<references>none</references>" in snippet


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


def test_get_tools_returns_only_instructions_when_no_scripts_or_references(minimal_skill: Skill) -> None:
    """Test that only get_skill_instructions is exposed for SKILL.md-only skills."""
    loader = MockSkillLoader([minimal_skill])
    skills = Skills(loaders=[loader])
    tools = skills.get_tools()

    assert len(tools) == 1
    assert tools[0].name == "get_skill_instructions"


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


# --- Mixed-Case Tests (some skills have scripts/references, others don't) ---


def test_mixed_skills_system_prompt_and_tools(sample_skill: Skill, minimal_skill: Skill) -> None:
    """When mixing skills with and without scripts/references, system prompt shows
    correct metadata for each skill and all three tools are exposed."""
    loader = MockSkillLoader([sample_skill, minimal_skill])
    skills = Skills(loaders=[loader])
    snippet = skills.get_system_prompt_snippet()

    assert "<name>test-skill</name>" in snippet
    assert "<name>minimal-skill</name>" in snippet

    assert "helper.py" in snippet
    assert "<scripts>none</scripts>" in snippet
    assert "guide.md" in snippet
    assert "<references>none</references>" in snippet

    assert "get_skill_script" in snippet
    assert "get_skill_reference" in snippet

    assert skills._has_any_scripts() is True
    assert skills._has_any_references() is True

    tool_names = {t.name for t in skills.get_tools()}
    assert tool_names == {"get_skill_instructions", "get_skill_reference", "get_skill_script"}


def test_mixed_scripts_only_and_refs_only_skills() -> None:
    """A mix where one skill has scripts but no references and another has
    references but no scripts — each block is rendered correctly and both tools exposed."""
    scripts_only = Skill(
        name="scripts-only-skill",
        description="A skill with scripts but no references",
        instructions="Use the scripts",
        source_path="/scripts-only",
        scripts=["run.sh"],
        references=[],
    )
    refs_only = Skill(
        name="refs-only-skill",
        description="A skill with references but no scripts",
        instructions="Read the references",
        source_path="/refs-only",
        scripts=[],
        references=["readme.md"],
    )

    loader = MockSkillLoader([scripts_only, refs_only])
    skills = Skills(loaders=[loader])
    snippet = skills.get_system_prompt_snippet()

    assert "<scripts>run.sh</scripts>" in snippet
    assert "<references>readme.md</references>" in snippet
    assert "<scripts>none</scripts>" in snippet
    assert "<references>none</references>" in snippet

    tool_names = {t.name for t in skills.get_tools()}
    assert "get_skill_script" in tool_names
    assert "get_skill_reference" in tool_names


def test_no_skills_have_scripts_or_references(minimal_skill: Skill) -> None:
    """When no loaded skill has scripts or references, helpers return False and
    only get_skill_instructions is exposed."""
    another_minimal = Skill(
        name="another-minimal",
        description="Also no assets",
        instructions="Nothing here",
        source_path="/other",
    )
    loader = MockSkillLoader([minimal_skill, another_minimal])
    skills = Skills(loaders=[loader])

    assert skills._has_any_scripts() is False
    assert skills._has_any_references() is False

    tool_names = {t.name for t in skills.get_tools()}
    assert "get_skill_script" not in tool_names
    assert "get_skill_reference" not in tool_names
    assert "get_skill_instructions" in tool_names


def test_mixed_skill_script_call_on_skillmd_only_skill_clear_error(sample_skill: Skill, minimal_skill: Skill) -> None:
    """In a mixed skill set all three tools are registered, but calling
    get_skill_script on a SKILL.md-only skill returns a clear error."""
    loader = MockSkillLoader([sample_skill, minimal_skill])
    skills = Skills(loaders=[loader])

    tool_names = {t.name for t in skills.get_tools()}
    assert tool_names == {"get_skill_instructions", "get_skill_reference", "get_skill_script"}

    result = json.loads(skills._get_skill_script("minimal-skill", "some.py"))
    assert result["error"] == "Skill 'minimal-skill' has no scripts"
    assert result["available_scripts"] == []


def test_mixed_skill_reference_call_on_skillmd_only_skill_clear_error(
    sample_skill: Skill, minimal_skill: Skill
) -> None:
    """Calling get_skill_reference on a SKILL.md-only skill in a mixed set
    returns a clear 'has no references' error."""
    loader = MockSkillLoader([sample_skill, minimal_skill])
    skills = Skills(loaders=[loader])

    result = json.loads(skills._get_skill_reference("minimal-skill", "guide.md"))
    assert result["error"] == "Skill 'minimal-skill' has no references"
    assert result["available_references"] == []


def test_mixed_skill_null_path_on_skillmd_only_skill_clear_error(sample_skill: Skill, minimal_skill: Skill) -> None:
    """Even without a path argument, a SKILL.md-only skill's missing assets are
    reported directly instead of a generic 'path is required' error."""
    loader = MockSkillLoader([sample_skill, minimal_skill])
    skills = Skills(loaders=[loader])

    script_result = json.loads(skills._get_skill_script("minimal-skill", None))
    assert script_result["error"] == "Skill 'minimal-skill' has no scripts"

    ref_result = json.loads(skills._get_skill_reference("minimal-skill", None))
    assert ref_result["error"] == "Skill 'minimal-skill' has no references"


def test_mixed_skill_asset_errors_still_reported_for_skill_with_assets(
    sample_skill: Skill, minimal_skill: Skill
) -> None:
    """In a mixed set, a skill that has assets keeps the existing error paths."""
    loader = MockSkillLoader([sample_skill, minimal_skill])
    skills = Skills(loaders=[loader])

    script_result = json.loads(skills._get_skill_script("test-skill", "nonexistent.py"))
    assert "not found" in script_result["error"].lower()
    assert script_result["available_scripts"] == ["helper.py", "runner.sh"]

    ref_result = json.loads(skills._get_skill_reference("test-skill", "nonexistent.md"))
    assert "not found" in ref_result["error"].lower()
    assert ref_result["available_references"] == ["guide.md", "api-docs.md"]


# --- System Prompt IMPORTANT Block Tests ---


def test_no_assets_important_block_mentions_only_instructions(minimal_skill: Skill) -> None:
    """When no skill has scripts or references, the IMPORTANT block tells the
    model to only use get_skill_instructions."""
    loader = MockSkillLoader([minimal_skill])
    skills = Skills(loaders=[loader])
    snippet = skills.get_system_prompt_snippet()

    assert "Only use `get_skill_instructions`" in snippet
    assert "unless the available skills metadata shows additional files" in snippet


def test_no_assets_important_block_does_not_mention_script_or_reference(minimal_skill: Skill) -> None:
    """In the all-no-assets case, the IMPORTANT block must not mention
    get_skill_script or get_skill_reference."""
    loader = MockSkillLoader([minimal_skill])
    skills = Skills(loaders=[loader])
    snippet = skills.get_system_prompt_snippet()

    important_section = snippet.split("## IMPORTANT")[1].split("## Available Skills")[0]
    assert "get_skill_script" not in important_section
    assert "get_skill_reference" not in important_section


def test_get_system_prompt_shows_none_for_all_skills_assets(minimal_skill: Skill) -> None:
    """All-no-assets skills each render <scripts>none</scripts> and
    <references>none</references>."""
    loader = MockSkillLoader([minimal_skill])
    skills = Skills(loaders=[loader])
    snippet = skills.get_system_prompt_snippet()

    assert snippet.count("<scripts>none</scripts>") == 1
    assert snippet.count("<references>none</references>") == 1


# --- LocalSkills Empty-Asset Normalization Tests ---


def test_local_skills_skillmd_only_produces_empty_scripts_and_references(tmp_path: Path) -> None:
    """A skill folder with only SKILL.md (no scripts/ or references/ dirs)
    should produce Skill objects with empty-list scripts and references."""
    skill_dir = tmp_path / "bare-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: bare-skill
description: A skill with no assets
---
# Bare Skill

Just instructions, no scripts or references.
"""
    )

    loader = LocalSkills(str(skill_dir))
    skills_list = loader.load()

    assert len(skills_list) == 1
    skill = skills_list[0]
    assert skill.name == "bare-skill"
    assert skill.scripts == []
    assert skill.references == []
    assert isinstance(skill.scripts, list)
    assert isinstance(skill.references, list)


def test_local_skills_empty_dirs_produce_empty_lists(tmp_path: Path) -> None:
    """A skill folder with empty scripts/ and references/ dirs should
    produce empty lists, not None."""
    skill_dir = tmp_path / "empty-dirs-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: empty-dirs-skill
description: Skill with empty asset dirs
---
Instructions here.
"""
    )
    (skill_dir / "scripts").mkdir()
    (skill_dir / "references").mkdir()

    loader = LocalSkills(str(skill_dir))
    skills_list = loader.load()

    assert len(skills_list) == 1
    skill = skills_list[0]
    assert skill.scripts == []
    assert skill.references == []


def test_local_skills_skillmd_only_has_no_scripts_or_references_tools(tmp_path: Path) -> None:
    """When loaded via LocalSkills, a SKILL.md-only skill should result in
    only get_skill_instructions being exposed."""
    skill_dir = tmp_path / "bare-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: bare-skill
description: Minimal skill
---
Instructions.
"""
    )

    loader = LocalSkills(str(skill_dir))
    skills_obj = Skills(loaders=[loader])
    tool_names = {t.name for t in skills_obj.get_tools()}

    assert tool_names == {"get_skill_instructions"}
    assert skills_obj._has_any_scripts() is False
    assert skills_obj._has_any_references() is False


# --- Dedup: get_skill_instructions Already-Provided Tests ---


def test_get_skill_instructions_first_call_no_dedup_flag(mock_loader: MockSkillLoader) -> None:
    """The first call for a skill should return full instructions with no
    'instructions_already_provided' flag."""
    skills = Skills(loaders=[mock_loader])
    result = json.loads(skills._get_skill_instructions("test-skill"))

    assert result["skill_name"] == "test-skill"
    assert "instructions" in result
    assert "instructions_already_provided" not in result
    assert "note" not in result


def test_get_skill_instructions_second_call_omits_full_instructions(mock_loader: MockSkillLoader) -> None:
    """A second call for the same skill should not resend the full instructions
    body; instead it returns 'instructions_already_provided': True and a note."""
    skills = Skills(loaders=[mock_loader])

    skills._get_skill_instructions("test-skill")

    result = json.loads(skills._get_skill_instructions("test-skill"))
    assert result["instructions_already_provided"] is True
    assert "note" in result
    assert "already loaded" in result["note"]
    assert "instructions" not in result
    assert "description" not in result
    assert result["available_scripts"] == ["helper.py", "runner.sh"]
    assert result["available_references"] == ["guide.md", "api-docs.md"]


def test_get_skill_instructions_different_skills_independent(mock_loader_multiple: MockSkillLoader) -> None:
    """Dedup tracking is per-skill: calling one skill doesn't flag another."""
    skills = Skills(loaders=[mock_loader_multiple])

    skills._get_skill_instructions("test-skill")

    result = json.loads(skills._get_skill_instructions("minimal-skill"))
    assert "instructions_already_provided" not in result


def test_get_skill_instructions_reload_clears_tracking(mock_loader: MockSkillLoader) -> None:
    """reload() should clear the dedup tracking set."""
    skills = Skills(loaders=[mock_loader])

    skills._get_skill_instructions("test-skill")
    result = json.loads(skills._get_skill_instructions("test-skill"))
    assert result["instructions_already_provided"] is True
    assert "instructions" not in result

    skills.reload()

    result = json.loads(skills._get_skill_instructions("test-skill"))
    assert "instructions_already_provided" not in result
    assert "instructions" in result
    assert "Follow these instructions" in result["instructions"]


def test_get_skill_instructions_not_found_never_tracked(mock_loader: MockSkillLoader) -> None:
    """A failed lookup (skill not found) should not be recorded as provided."""
    skills = Skills(loaders=[mock_loader])

    skills._get_skill_instructions("nonexistent")

    result = json.loads(skills._get_skill_instructions("test-skill"))
    assert "instructions_already_provided" not in result


def test_get_skill_instructions_reset_for_run_restores_full_instructions(mock_loader: MockSkillLoader) -> None:
    skills = Skills(loaders=[mock_loader])

    result = json.loads(skills._get_skill_instructions("test-skill"))
    assert "instructions" in result
    assert "instructions_already_provided" not in result

    result = json.loads(skills._get_skill_instructions("test-skill"))
    assert result["instructions_already_provided"] is True
    assert "instructions" not in result

    skills.reset_for_run()

    result = json.loads(skills._get_skill_instructions("test-skill"))
    assert "instructions" in result
    assert "instructions_already_provided" not in result


def test_reset_for_run_safe_without_prior_calls(mock_loader: MockSkillLoader) -> None:
    skills = Skills(loaders=[mock_loader])

    skills.reset_for_run()

    result = json.loads(skills._get_skill_instructions("test-skill"))
    assert "instructions" in result
    assert "instructions_already_provided" not in result
