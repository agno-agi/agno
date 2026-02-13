import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from agno.skills.errors import SkillValidationError
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.skills.utils import is_safe_path, read_file_safe, run_script
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning


class Skills:
    """Orchestrates skill loading and provides tools for agents to access skills.

    The Skills class is responsible for:
    1. Loading skills from various sources (loaders)
    2. Providing methods to access loaded skills
    3. Generating tools for agents to use skills
    4. Creating system prompt snippets with available skills metadata

    Args:
        loaders: List of SkillLoader instances to load skills from.
    """

    def __init__(self, loaders: List[SkillLoader]):
        self.loaders = loaders
        self._skills: Dict[str, Skill] = {}
        self._load_skills()

    def _load_skills(self) -> None:
        """Load skills from all loaders.

        Raises:
            SkillValidationError: If any skill fails validation.
        """
        for loader in self.loaders:
            try:
                skills = loader.load()
                for skill in skills:
                    if skill.name in self._skills:
                        log_warning(f"Duplicate skill name '{skill.name}', overwriting with newer version")
                    self._skills[skill.name] = skill
            except SkillValidationError:
                raise  # Re-raise validation errors as hard failures
            except Exception as e:
                log_warning(f"Error loading skills from {loader}: {e}")

        log_debug(f"Loaded {len(self._skills)} total skills")

    def reload(self) -> None:
        """Reload skills from all loaders, clearing existing skills.

        Raises:
            SkillValidationError: If any skill fails validation.
        """
        self._skills.clear()
        self._load_skills()

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name.

        Args:
            name: The name of the skill to retrieve.

        Returns:
            The Skill object if found, None otherwise.
        """
        return self._skills.get(name)

    def get_all_skills(self) -> List[Skill]:
        """Get all loaded skills.

        Returns:
            A list of all loaded Skill objects.
        """
        return list(self._skills.values())

    def get_skill_names(self) -> List[str]:
        """Get the names of all loaded skills.

        Returns:
            A list of skill names.
        """
        return list(self._skills.keys())

    def get_system_prompt_snippet(self) -> str:
        """Generate a system prompt snippet with available skills metadata.

        This creates an XML-formatted snippet that provides the agent with
        information about available skills without including the full instructions.

        Returns:
            An XML-formatted string with skills metadata.
        """
        if not self._skills:
            return ""

        lines = [
            "<skills_system>",
            "",
            "## What are Skills?",
            "Skills are packages of domain expertise that extend your capabilities. Each skill contains:",
            "- **Instructions**: Detailed guidance on when and how to apply the skill",
            "- **Scripts**: Executable code templates you can use or adapt",
            "- **References**: Supporting documentation (guides, cheatsheets, examples)",
            "",
            "## IMPORTANT: How to Use Skills",
            "**Skill names are NOT callable functions.** You cannot call a skill directly by its name.",
            "Instead, you MUST use the provided skill access tools:",
            "",
            "1. `get_skill_instructions(skill_name)` - Load the full instructions for a skill",
            "2. `get_skill_reference(skill_name, reference_path)` - Access specific documentation",
            "3. `get_skill_script(skill_name, script_path, execute=False)` - Read or run scripts",
            "",
            "## Progressive Discovery Workflow",
            "1. **Browse**: Review the skill summaries below to understand what's available",
            "2. **Load**: When a task matches a skill, call `get_skill_instructions(skill_name)` first",
            "3. **Reference**: Use `get_skill_reference` to access specific documentation as needed",
            "4. **Scripts**: Use `get_skill_script` to read or execute scripts from a skill",
            "",
            "**IMPORTANT**: References are documentation files (NOT executable). Only use `get_skill_script` when `<scripts>` lists actual script files. If `<scripts>none</scripts>`, do NOT call `get_skill_script`.",
            "",
            "This approach ensures you only load detailed instructions when actually needed.",
            "",
            "## Available Skills",
        ]
        for skill in self._skills.values():
            lines.append("<skill>")
            lines.append(f"  <name>{skill.name}</name>")
            lines.append(f"  <description>{skill.description}</description>")
            if skill.scripts:
                script_names = [s["name"] if isinstance(s, dict) else s for s in skill.scripts]
                lines.append(f"  <scripts>{', '.join(script_names)}</scripts>")
            else:
                # Explicitly indicate no scripts to prevent model confusion
                lines.append("  <scripts>none</scripts>")
            if skill.references:
                ref_names = [r["name"] if isinstance(r, dict) else r for r in skill.references]
                lines.append(f"  <references>{', '.join(ref_names)}</references>")
            lines.append("</skill>")
        lines.append("")
        lines.append("</skills_system>")

        return "\n".join(lines)

    def get_tools(self) -> List[Function]:
        """Get the tools for accessing skills.

        Returns:
            A list of Function objects that agents can use to access skills.
        """
        tools: List[Function] = []

        # Tool: get_skill_instructions
        tools.append(
            Function(
                name="get_skill_instructions",
                description="Load the full instructions for a skill. Use this when you need to follow a skill's guidance.",
                entrypoint=self._get_skill_instructions,
            )
        )

        # Tool: get_skill_reference
        tools.append(
            Function(
                name="get_skill_reference",
                description="Load a reference document from a skill's references. Use this to access detailed documentation.",
                entrypoint=self._get_skill_reference,
            )
        )

        # Tool: get_skill_script
        tools.append(
            Function(
                name="get_skill_script",
                description="Read or execute a script from a skill. Set execute=True to run the script and get output, or execute=False (default) to read the script content.",
                entrypoint=self._get_skill_script,
            )
        )

        return tools

    def _get_skill_instructions(self, skill_name: str) -> str:
        """Load the full instructions for a skill.

        Args:
            skill_name: The name of the skill to get instructions for.

        Returns:
            A JSON string with the skill's instructions and metadata.
        """
        skill = self.get_skill(skill_name)
        if skill is None:
            available = ", ".join(self.get_skill_names())
            return json.dumps(
                {
                    "error": f"Skill '{skill_name}' not found",
                    "available_skills": available,
                }
            )

        return json.dumps(
            {
                "skill_name": skill.name,
                "description": skill.description,
                "instructions": skill.instructions,
                "available_scripts": skill.scripts,
                "available_references": skill.references,
            }
        )

    def _get_skill_reference(self, skill_name: str, reference_path: str) -> str:
        """Load a reference document from a skill.

        Args:
            skill_name: The name of the skill.
            reference_path: The filename of the reference document.

        Returns:
            A JSON string with the reference content.
        """
        skill = self.get_skill(skill_name)
        if skill is None:
            available = ", ".join(self.get_skill_names())
            return json.dumps(
                {
                    "error": f"Skill '{skill_name}' not found",
                    "available_skills": available,
                }
            )

        if reference_path not in skill.references:
            return json.dumps(
                {
                    "error": f"Reference '{reference_path}' not found in skill '{skill_name}'",
                    "available_references": skill.references,
                }
            )

        # Validate path to prevent path traversal attacks
        refs_dir = Path(skill.source_path) / "references"
        if not is_safe_path(refs_dir, reference_path):
            return json.dumps(
                {
                    "error": f"Invalid reference path: '{reference_path}'",
                    "skill_name": skill_name,
                }
            )

        # Load the reference file
        ref_file = refs_dir / reference_path
        try:
            content = read_file_safe(ref_file)
            return json.dumps(
                {
                    "skill_name": skill_name,
                    "reference_path": reference_path,
                    "content": content,
                }
            )
        except Exception as e:
            return json.dumps(
                {
                    "error": f"Error reading reference file: {e}",
                    "skill_name": skill_name,
                    "reference_path": reference_path,
                }
            )

    def _get_skill_script(
        self,
        skill_name: str,
        script_path: str,
        execute: bool = False,
        args: Optional[List[str]] = None,
        timeout: int = 30,
    ) -> str:
        """Read or execute a script from a skill.

        Args:
            skill_name: The name of the skill.
            script_path: The filename of the script.
            execute: If True, execute the script. If False (default), return content.
            args: Optional list of arguments to pass to the script (only used if execute=True).
            timeout: Maximum execution time in seconds (default: 30, only used if execute=True).

        Returns:
            A JSON string with either the script content or execution results.
        """
        skill = self.get_skill(skill_name)
        if skill is None:
            available = ", ".join(self.get_skill_names())
            return json.dumps(
                {
                    "error": f"Skill '{skill_name}' not found",
                    "available_skills": available,
                }
            )

        if script_path not in skill.scripts:
            return json.dumps(
                {
                    "error": f"Script '{script_path}' not found in skill '{skill_name}'",
                    "available_scripts": skill.scripts,
                }
            )

        # Validate path to prevent path traversal attacks
        scripts_dir = Path(skill.source_path) / "scripts"
        if not is_safe_path(scripts_dir, script_path):
            return json.dumps(
                {
                    "error": f"Invalid script path: '{script_path}'",
                    "skill_name": skill_name,
                }
            )

        script_file = scripts_dir / script_path

        if not execute:
            # Read mode: return script content
            try:
                content = read_file_safe(script_file)
                return json.dumps(
                    {
                        "skill_name": skill_name,
                        "script_path": script_path,
                        "content": content,
                    }
                )
            except Exception as e:
                return json.dumps(
                    {
                        "error": f"Error reading script file: {e}",
                        "skill_name": skill_name,
                        "script_path": script_path,
                    }
                )

        # Execute mode: run the script
        try:
            result = run_script(
                script_path=script_file,
                args=args,
                timeout=timeout,
                cwd=Path(skill.source_path),
            )
            return json.dumps(
                {
                    "skill_name": skill_name,
                    "script_path": script_path,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                }
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "error": f"Script execution timed out after {timeout} seconds",
                    "skill_name": skill_name,
                    "script_path": script_path,
                }
            )
        except FileNotFoundError as e:
            return json.dumps(
                {
                    "error": f"Interpreter or script not found: {e}",
                    "skill_name": skill_name,
                    "script_path": script_path,
                }
            )
        except Exception as e:
            return json.dumps(
                {
                    "error": f"Error executing script: {e}",
                    "skill_name": skill_name,
                    "script_path": script_path,
                }
            )
