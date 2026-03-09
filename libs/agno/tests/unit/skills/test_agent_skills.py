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
