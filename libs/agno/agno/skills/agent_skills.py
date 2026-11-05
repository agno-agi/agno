import json
import subprocess
import threading
from collections import OrderedDict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional

from agno.exceptions import PathSecurityError
from agno.run.base import RunContext
from agno.skills.errors import SkillValidationError
from agno.skills.executor import LocalSkillExecutor, SkillExecutor
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.skills.utils import create_skill_files, read_file_safe
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning
from agno.utils.path_safety import safe_join_relative_path

# Views kept per Skills object: one must survive from a user's prompt build to that run's
# tool calls; past the limit the oldest is dropped and comes back with one read.
_USER_VIEWS_KEPT = 128


class Skills:
    """Orchestrates skill loading and provides tools for agents to access skills.

    The Skills class is responsible for:
    1. Loading skills from various sources (loaders)
    2. Providing methods to access loaded skills
    3. Generating tools for agents to use skills
    4. Creating system prompt snippets with available skills metadata

    Args:
        loaders: List of SkillLoader instances to load skills from.
        executor: Runs a skill's scripts. Defaults to LocalSkillExecutor, which runs them as
            subprocesses on this host.
    """

    def __init__(
        self,
        loaders: List[SkillLoader],
        executor: Optional[SkillExecutor] = None,
    ):
        self.loaders = loaders
        self.executor = executor if executor is not None else LocalSkillExecutor()
        self._skills: Dict[str, Skill] = {}
        # Each loader's last successful result by index: a per-request refresh re-runs only
        # the loaders marked for it and merges the rest from here.
        self._loader_results: Dict[int, List[Skill]] = {}
        # One view per user from owner-scoped refreshes, newest last, kept apart from _skills.
        self._user_skills: "OrderedDict[str, Dict[str, Skill]]" = OrderedDict()
        # Guards the writes above and the refresh numbering; never held across a loader's read.
        self._refresh_lock = threading.Lock()
        self._refresh_count = 0
        # The last committed refresh per view (None is the shared mapping), forgotten with the
        # view, so a refresh older than an evicted view's last one still lands.
        self._committed_refreshes: Dict[Optional[str], int] = {}
        self._load_skills()

    def __getstate__(self) -> Dict[str, Any]:
        # A lock cannot be copied or pickled; a copy gets a lock of its own.
        state = self.__dict__.copy()
        state.pop("_refresh_lock", None)
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._refresh_lock = threading.Lock()

    def _load_skills(self) -> None:
        """Load skills from all loaders, replacing the current mapping in one step.

        Raises:
            SkillValidationError: If any skill fails validation.
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
        # Swapped once at the end: a reader mid-reload sees the previous mapping, never a partial one.
        with self._refresh_lock:
            self._loader_results = results
            self._skills = merged
        log_debug(f"Loaded {len(self._skills)} total skills")

    def _merge_loader_results(self, results: Dict[int, List[Skill]]) -> Dict[str, Skill]:
        """Merge per-loader results into one name-keyed mapping, later loaders winning."""
        merged: Dict[str, Skill] = {}
        for index in range(len(self.loaders)):
            for skill in results.get(index, []):
                if skill.name in merged:
                    log_warning(f"Duplicate skill name '{skill.name}', overwriting with newer version")
                merged[skill.name] = skill
        return merged

    def _refresh_loaders(self, user_id: Optional[str] = None) -> None:
        """Re-run the refresh_per_request loaders into the user's view, or the shared mapping without a user.

        Any failure keeps the previous state, so a request mid-outage serves the last loaded skills.
        """
        if not any(loader.refresh_per_request for loader in self.loaders):
            return
        with self._refresh_lock:
            self._refresh_count += 1
            refresh = self._refresh_count
        fresh: Dict[int, List[Skill]] = {}
        # The shared rows of a loader the shared mapping never loaded, read alongside the
        # user's: the eager load cannot await an async database, and under user-only
        # traffic nothing else would fill what get_skill_names and a view-less tool call read.
        shared: Dict[int, List[Skill]] = {}
        for index, loader in enumerate(self.loaders):
            if not loader.refresh_per_request:
                continue
            try:
                # Only owner-scoped loaders receive the user; the rest are called with no user.
                fresh[index] = loader.load(user_id=user_id) if loader.owner_scoped else loader.load()
                if user_id is not None and index not in self._loader_results:
                    shared[index] = loader.load() if loader.owner_scoped else fresh[index]
            except Exception as e:
                log_warning(f"Error refreshing skills from {loader}, keeping the last loaded skills: {str(e)}")

        if fresh:
            self._commit_refresh(user_id, refresh, fresh, shared)

    def _commit_refresh(
        self,
        user_id: Optional[str],
        refresh: int,
        fresh: Dict[int, List[Skill]],
        shared: Dict[int, List[Skill]],
    ) -> None:
        """Store a refresh: the shared mapping without a user, else that user's view alone.

        Under the lock and after every read: a sibling that committed meanwhile is built on,
        not rolled back, and a refresh of this view that started later and already committed
        wins, on either path. Requests without a user share the one no-user view and settle
        the same way.
        """
        with self._refresh_lock:
            if refresh < self._committed_refreshes.get(user_id, 0):
                return
            results = {**self._loader_results, **fresh}
            merged = self._merge_loader_results(results)
            if user_id is None:
                self._loader_results = results
                self._skills = merged
            else:
                # Only what is still missing: a no-user refresh may have filled the rest meanwhile.
                shared = {index: rows for index, rows in shared.items() if index not in self._loader_results}
                if shared:
                    self._loader_results = {**self._loader_results, **shared}
                    self._skills = self._merge_loader_results(self._loader_results)
                self._user_skills[user_id] = merged
                self._user_skills.move_to_end(user_id)
                while len(self._user_skills) > _USER_VIEWS_KEPT:
                    evicted, _ = self._user_skills.popitem(last=False)
                    self._committed_refreshes.pop(evicted, None)
            self._committed_refreshes[user_id] = refresh

    def _view_for(self, user_id: Optional[str]) -> Dict[str, Skill]:
        """The mapping a request reads: the user's own view, else the shared mapping."""
        if user_id is None:
            return self._skills
        return self._user_skills.get(user_id, self._skills)

    def _view_for_call(self, run_context: Optional[RunContext]) -> Dict[str, Skill]:
        """The mapping a tool call reads, resolved first when its user has no view yet.

        A resumed run or a dropped entry reaches a tool with no view behind it. The tools
        are sync, so an async database cannot be read here: the call answers from the
        shared mapping until that user's prompt is built.
        """
        user_id = run_context.user_id if run_context is not None else None
        if user_id is not None and user_id not in self._user_skills:
            self._refresh_loaders(user_id=user_id)
        return self._view_for(user_id)

    async def _arefresh_loaders(self, user_id: Optional[str] = None) -> None:
        """Async twin of _refresh_loaders: awaits each refreshing loader's aload."""
        if not any(loader.refresh_per_request for loader in self.loaders):
            return
        with self._refresh_lock:
            self._refresh_count += 1
            refresh = self._refresh_count
        fresh: Dict[int, List[Skill]] = {}
        shared: Dict[int, List[Skill]] = {}
        for index, loader in enumerate(self.loaders):
            if not loader.refresh_per_request:
                continue
            try:
                fresh[index] = await loader.aload(user_id=user_id) if loader.owner_scoped else await loader.aload()
                if user_id is not None and index not in self._loader_results:
                    shared[index] = await loader.aload() if loader.owner_scoped else fresh[index]
            except Exception as e:
                log_warning(f"Error refreshing skills from {loader}, keeping the last loaded skills: {str(e)}")

        if fresh:
            self._commit_refresh(user_id, refresh, fresh, shared)

    def to_config(self) -> Optional[Dict[str, Any]]:
        """The stored form of these skills: references to database skills, never their content.

        A reference with no version is pinned to the version this object loaded, so a saved
        agent runs the skill it was tested with. Skills from other loaders are not saved.

        Returns:
            The config block, or None when no loader reads from the database.
        """
        from agno.skills.component import SkillRef
        from agno.skills.loaders.db import DbSkills

        refs: List[Dict[str, Any]] = []
        for loader in self.loaders:
            if not isinstance(loader, DbSkills):
                log_warning(f"Skills from {type(loader).__name__} are not stored in the database and will not be saved")
                continue
            for ref in loader.refs:
                version = ref.version if ref.version is not None else loader.resolved_versions.get(ref.id)
                refs.append(SkillRef(ref.id, version).to_dict())
        if not refs:
            return None
        config: Dict[str, Any] = {"refs": refs}
        # An executor is code and cannot be stored; recording it stops a reload from running scripts on the host.
        if type(self.executor) is not LocalSkillExecutor:
            config["custom_executor"] = True
        return config

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        *,
        db: Optional[Any],
        strict: bool = False,
        label: str = "Component",
        user_id: Optional[str] = None,
    ) -> Optional["Skills"]:
        """Rebuild Skills from a stored config block by resolving its references against ``db``.

        Strict loading refuses a reference that resolves to nothing. Lenient loading skips it
        with a warning. A config saved with a custom executor never loads with the default one.

        Raises:
            ComponentRehydrationError: If strict and the skills cannot be fully restored.
        """
        from agno.exceptions import ComponentRehydrationError
        from agno.skills.component import SkillRef
        from agno.skills.loaders.db import DbSkills

        def refuse(message: str) -> None:
            if strict:
                raise ComponentRehydrationError(f"{label} {message}")
            log_warning(f"{label} {message}; loading it without skills")

        if config.get("custom_executor"):
            refuse("was saved with a custom skill executor, which cannot be restored")
            return None
        if db is None:
            refuse("references database skills but no database was provided")
            return None

        loader = DbSkills(db, [SkillRef.from_dict(ref) for ref in config.get("refs") or []], user_id=user_id)
        skills = cls(loaders=[loader])
        if strict and not loader.loaded:
            raise ComponentRehydrationError(f"{label} skills could not be read from the database")
        if strict and loader.missing:
            missing = ", ".join(f"'{ref.id}'" + (f" v{ref.version}" if ref.version else "") for ref in loader.missing)
            raise ComponentRehydrationError(f"{label} references skills that are not published: {missing}")
        return skills

    def reload(self) -> None:
        """Reload skills from all loaders, replacing the existing skills.

        Raises:
            SkillValidationError: If any skill fails validation.
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

    def get_system_prompt_snippet(self, user_id: Optional[str] = None) -> str:
        """Generate a system prompt snippet with available skills metadata.

        This creates an XML-formatted snippet that provides the agent with
        information about available skills without including the full instructions.
        A refresh_per_request loader (DbSkills) does its blocking read here; the async
        message path awaits it through aget_system_prompt_snippet instead.

        Returns:
            An XML-formatted string with skills metadata.
        """
        # The per-request read of database-backed loaders, once per run with the system prompt.
        self._refresh_loaders(user_id=user_id)
        return self._build_system_prompt_snippet(self._view_for(user_id))

    async def aget_system_prompt_snippet(self, user_id: Optional[str] = None) -> str:
        """Async twin of get_system_prompt_snippet: the refresh awaits the database read."""
        await self._arefresh_loaders(user_id=user_id)
        return self._build_system_prompt_snippet(self._view_for(user_id))

    def _build_system_prompt_snippet(self, skills: Dict[str, Skill]) -> str:
        """Render a skill mapping as the system prompt snippet."""
        if not skills:
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
        for skill in skills.values():
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

    def _get_skill_instructions(self, skill_name: str, run_context: Optional[RunContext] = None) -> str:
        """Load the full instructions for a skill.

        Args:
            skill_name: The name of the skill to get instructions for.

        Returns:
            A JSON string with the skill's instructions and metadata.
        """
        skills = self._view_for_call(run_context)
        skill = skills.get(skill_name)
        if skill is None:
            available = ", ".join(skills)
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

    def _get_skill_reference(
        self, skill_name: str, reference_path: Optional[str] = None, run_context: Optional[RunContext] = None
    ) -> str:
        """Load a reference document from a skill.

        Args:
            skill_name: The name of the skill.
            reference_path: The filename of the reference document.

        Returns:
            A JSON string with the reference content.
        """
        skills = self._view_for_call(run_context)
        skill = skills.get(skill_name)
        if skill is None:
            available = ", ".join(skills)
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
            # Content-carrying: every declared filename has content (Skill.__post_init__), so this cannot miss.
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
        run_context: Optional[RunContext] = None,
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
        skills = self._view_for_call(run_context)
        skill = skills.get(skill_name)
        if skill is None:
            available = ", ".join(skills)
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

        # Executing needs real files: written to a temporary skill-shaped folder for the run.
        with TemporaryDirectory(prefix="agno-skill-") as temp_dir:
            # Resolved so the script path and cwd agree, as they do for a path-backed skill.
            skill_dir = Path(temp_dir).resolve()
            try:
                create_skill_files(skill, skill_dir)
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
