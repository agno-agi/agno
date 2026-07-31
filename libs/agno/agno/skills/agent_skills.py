import asyncio
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Literal, Optional

from agno.exceptions import PathSecurityError
from agno.skills.errors import SkillError, SkillValidationError
from agno.skills.executor import LocalSkillExecutor, SkillExecutor
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.skills.utils import materialize_skill_contents, read_file_safe
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning
from agno.utils.path_safety import safe_join_relative_path


class Skills:
    """Orchestrates skill loading and provides tools for agents to access skills.

    The Skills class is responsible for:
    1. Loading skills from various sources (loaders)
    2. Providing methods to access loaded skills
    3. Generating tools for agents to use skills
    4. Creating system prompt snippets with available skills metadata

    Args:
        loaders: List of SkillLoader instances to load skills from.
        on_duplicate: What to do when two loaders provide the same skill name. "warn" (default)
            keeps the last one loaded and logs a warning; "raise" rejects the collision at load
            and reload. A per-request refresh that would collide keeps the previous mapping
            instead of raising mid-request.
        executor: Runs a skill's scripts. Defaults to LocalSkillExecutor, which runs them as
            subprocesses on this host.
    """

    def __init__(
        self,
        loaders: List[SkillLoader],
        on_duplicate: Literal["warn", "raise"] = "warn",
        executor: Optional[SkillExecutor] = None,
    ):
        if on_duplicate not in ("warn", "raise"):
            raise ValueError(f"Invalid on_duplicate {on_duplicate!r}: expected 'warn' or 'raise'")

        self.loaders = loaders
        self.on_duplicate = on_duplicate
        self.executor = executor if executor is not None else LocalSkillExecutor()
        self._skills: Dict[str, Skill] = {}
        # Each loader's last successful result, keyed by its index in self.loaders. A
        # per-request refresh re-runs only the loaders marked for it and merges the rest
        # from here; a failed refresh falls back to it.
        self._loader_results: Dict[int, List[Skill]] = {}
        self._refresh_lock: Optional[asyncio.Lock] = None  # Lazily created lock for the async refresh
        self._load_skills()

    def _load_skills(self) -> None:
        """Load skills from all loaders, replacing the current mapping in one step.

        Raises:
            SkillValidationError: If any skill fails validation.
            SkillError: If on_duplicate is "raise" and two loaders provide the same skill name.
        """
        results: Dict[int, List[Skill]] = {}
        for index, loader in enumerate(self.loaders):
            try:
                results[index] = loader.load()
            except SkillValidationError:
                raise  # Re-raise validation errors as hard failures
            except Exception as e:
                log_warning(f"Error loading skills from {loader}: {str(e)}")

        merged = self._merge_loader_results(results)
        # Swap once, at the end: a reader during a reload sees the previous mapping rather than an
        # empty or half-filled one.
        self._loader_results = results
        self._skills = merged
        log_debug(f"Loaded {len(self._skills)} total skills")

    def _merge_loader_results(self, results: Dict[int, List[Skill]]) -> Dict[str, Skill]:
        """Merge per-loader results into one name-keyed mapping, later loaders winning.

        Raises:
            SkillError: If on_duplicate is "raise" and two loaders provide the same skill name.
        """
        merged: Dict[str, Skill] = {}
        for index, loader in enumerate(self.loaders):
            for skill in results.get(index, []):
                if skill.name in merged:
                    if self.on_duplicate == "raise":
                        raise SkillError(f"Duplicate skill name '{skill.name}' from loader {loader}")
                    log_warning(f"Duplicate skill name '{skill.name}', overwriting with newer version")
                merged[skill.name] = skill
        return merged

    def _refresh_loaders(self) -> None:
        """Re-run the loaders marked refresh_per_request and swap the rebuilt mapping in once.

        Any failure keeps the previous state: a request mid-outage serves the last
        loaded skills rather than an empty or partial set.
        """
        results = dict(self._loader_results)
        changed = False
        for index, loader in enumerate(self.loaders):
            if not loader.refresh_per_request:
                continue
            try:
                results[index] = loader.load()
                changed = True
            except Exception as e:
                log_warning(f"Error refreshing skills from {loader}, keeping the last loaded skills: {str(e)}")

        if not changed:
            return
        try:
            merged = self._merge_loader_results(results)
        except SkillError as e:
            log_warning(f"Error refreshing skills, keeping the last loaded skills: {str(e)}")
            return
        self._loader_results = results
        self._skills = merged

    @property
    def _async_refresh_lock(self) -> asyncio.Lock:
        """Lazily create an asyncio lock for serializing the async refresh."""
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        return self._refresh_lock

    async def _arefresh_loaders(self) -> None:
        """Async twin of _refresh_loaders: awaits each refreshing loader's aload.

        Any failure keeps the previous state: a request mid-outage serves the last
        loaded skills rather than an empty or partial set.
        """
        # Serialized, with the snapshot taken inside the lock: the awaits below
        # suspend, and a sibling request's refresh may commit while this one is
        # parked - committing a pre-await snapshot would roll that fresher state back.
        async with self._async_refresh_lock:
            results = dict(self._loader_results)
            changed = False
            for index, loader in enumerate(self.loaders):
                if not loader.refresh_per_request:
                    continue
                try:
                    results[index] = await loader.aload()
                    changed = True
                except Exception as e:
                    log_warning(f"Error refreshing skills from {loader}, keeping the last loaded skills: {str(e)}")

            if not changed:
                return
            try:
                merged = self._merge_loader_results(results)
            except SkillError as e:
                log_warning(f"Error refreshing skills, keeping the last loaded skills: {str(e)}")
                return
            self._loader_results = results
            self._skills = merged

    def reload(self) -> None:
        """Reload skills from all loaders, replacing the existing skills.

        Raises:
            SkillValidationError: If any skill fails validation.
            SkillError: If on_duplicate is "raise" and two loaders provide the same skill name.
        """
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

        With a refresh_per_request loader attached (DbSkills), building the snippet
        performs that loader's blocking database read; the async message path uses
        aget_system_prompt_snippet, which awaits it instead.

        Returns:
            An XML-formatted string with skills metadata.
        """
        # The once-per-request read of database-backed loaders: the system prompt is
        # built once per run, the same moment memory and learning already hit the db.
        self._refresh_loaders()
        return self._build_system_prompt_snippet()

    async def aget_system_prompt_snippet(self) -> str:
        """Async twin of get_system_prompt_snippet: the refresh awaits the database read.

        Returns:
            An XML-formatted string with skills metadata.
        """
        await self._arefresh_loaders()
        return self._build_system_prompt_snippet()

    def _build_system_prompt_snippet(self) -> str:
        """Render the loaded skill mapping as the system prompt snippet."""
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

    def _get_skill_reference(self, skill_name: str, reference_path: Optional[str] = None) -> str:
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

        if not reference_path:
            return json.dumps(
                {
                    "error": f"A reference_path is required to read a reference from skill '{skill_name}'",
                    "skill_name": skill_name,
                    "available_references": skill.references,
                }
            )

        if reference_path not in skill.references:
            return json.dumps(
                {
                    "error": f"Reference '{reference_path}' not found in skill '{skill_name}'",
                    "available_references": skill.references,
                }
            )

        if skill.source_path is None:
            # Content-carrying: the membership check above proved the filename is declared, and
            # Skill.__post_init__ proved every declared filename has content, so this cannot miss.
            return json.dumps(
                {
                    "skill_name": skill_name,
                    "reference_path": reference_path,
                    "content": (skill.reference_contents or {})[reference_path],
                }
            )

        # Validate and resolve path to prevent path traversal attacks
        refs_dir = Path(skill.source_path) / "references"
        try:
            ref_file = safe_join_relative_path(refs_dir, reference_path)
        except PathSecurityError:
            return json.dumps(
                {
                    "error": f"Invalid reference path: '{reference_path}'",
                    "skill_name": skill_name,
                }
            )
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
        script_path: Optional[str] = None,
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

        if not script_path:
            return json.dumps(
                {
                    "error": f"A script_path is required to read a script from skill '{skill_name}'",
                    "skill_name": skill_name,
                    "available_scripts": skill.scripts,
                }
            )

        if script_path not in skill.scripts:
            return json.dumps(
                {
                    "error": f"Script '{script_path}' not found in skill '{skill_name}'",
                    "available_scripts": skill.scripts,
                }
            )

        if skill.source_path is None:
            return self._content_skill_script(
                skill=skill,
                script_path=script_path,
                execute=execute,
                args=args,
                timeout=timeout,
            )

        # Validate and resolve path to prevent path traversal attacks
        scripts_dir = Path(skill.source_path) / "scripts"
        try:
            script_file = safe_join_relative_path(scripts_dir, script_path)
        except PathSecurityError:
            return json.dumps(
                {
                    "error": f"Invalid script path: '{script_path}'",
                    "skill_name": skill_name,
                }
            )

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
        return self._execute_script(
            skill_name=skill_name,
            script_path=script_path,
            script_file=script_file,
            cwd=Path(skill.source_path),
            args=args,
            timeout=timeout,
        )

    def _content_skill_script(
        self,
        *,
        skill: Skill,
        script_path: str,
        execute: bool,
        args: Optional[List[str]],
        timeout: int,
    ) -> str:
        """Read or execute a script whose content the skill carries instead of a source_path.

        The caller has already checked that ``script_path`` is one of the skill's declared
        scripts, and Skill.__post_init__ has already checked that every declared script has
        content, so the lookup below cannot miss.

        Args:
            skill: The content-carrying skill.
            script_path: The filename of the script.
            execute: If True, execute the script. If False, return content.
            args: Optional list of arguments to pass to the script (only used if execute=True).
            timeout: Maximum execution time in seconds (only used if execute=True).

        Returns:
            A JSON string with either the script content or execution results.
        """
        if not execute:
            return json.dumps(
                {
                    "skill_name": skill.name,
                    "script_path": script_path,
                    "content": (skill.script_contents or {})[script_path],
                }
            )

        # Executing needs a real file to hand the interpreter, so the skill's files are written to
        # a temporary directory shaped like a skill folder and thrown away once the script exits.
        with TemporaryDirectory(prefix="agno-skill-") as temp_dir:
            # Resolved, so the script path and the cwd agree the way they do for a path-backed
            # skill, whose source_path LocalSkills has already resolved.
            skill_dir = Path(temp_dir).resolve()
            try:
                materialize_skill_contents(skill, skill_dir)
                script_file = safe_join_relative_path(skill_dir / "scripts", script_path)
            except PathSecurityError:
                return json.dumps(
                    {
                        "error": f"Invalid script path: '{script_path}'",
                        "skill_name": skill.name,
                    }
                )
            except OSError as e:
                return json.dumps(
                    {
                        "error": f"Error writing skill files: {e}",
                        "skill_name": skill.name,
                        "script_path": script_path,
                    }
                )

            return self._execute_script(
                skill_name=skill.name,
                script_path=script_path,
                script_file=script_file,
                cwd=skill_dir,
                args=args,
                timeout=timeout,
            )

    def _execute_script(
        self,
        *,
        skill_name: str,
        script_path: str,
        script_file: Path,
        cwd: Path,
        args: Optional[List[str]],
        timeout: int,
    ) -> str:
        """Run a resolved script file and serialize the result.

        Args:
            skill_name: The name of the skill the script belongs to.
            script_path: The filename of the script, for the response payload.
            script_file: The resolved path of the script to run.
            cwd: Working directory for the script.
            args: Optional list of arguments to pass to the script.
            timeout: Maximum execution time in seconds.

        Returns:
            A JSON string with the execution results, or an error.
        """
        try:
            result = self.executor.run(
                script_file,
                args=args,
                timeout=timeout,
                cwd=cwd,
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
