import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.tools.function import Function
from agno.utils.log import log_debug, log_info, log_warning

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.models.base import Model


class UnsafeSkillError(Exception):
    """Raised when a skill contains potentially unsafe scripts.

    This exception is raised during skill loading when script safety verification
    is enabled and a script is detected to contain dangerous patterns.
    """

    pass


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

    def __init__(
        self,
        loaders: List[SkillLoader],
        dynamic: bool = True,
        verify_scripts: bool = True,
        verification_model: Optional["Model"] = None,
    ):
        """Initialize Skills orchestrator.

        Args:
            loaders: List of SkillLoader instances to load skills from.
            dynamic: If True (default), reload skills from loaders on every access.
                     Useful for DB-backed skills that may change at runtime.
            verify_scripts: If True (default), verify scripts for dangerous patterns
                     before loading. Raises UnsafeSkillError if suspicious code is found.
            verification_model: Optional model to use for LLM-based script verification.
                     If not provided, falls back to heuristic pattern matching.
        """
        self.loaders = loaders
        self.dynamic = dynamic
        self.verify_scripts = verify_scripts
        self.verification_model = verification_model
        self._skills: Dict[str, Skill] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Ensure skills are loaded from all loaders."""
        if self._loaded and not self.dynamic:
            return

        # Clear existing skills if reloading in dynamic mode
        if self.dynamic:
            self._skills.clear()

        for loader in self.loaders:
            try:
                skills = loader.load()
                for skill in skills:
                    # Verify scripts if enabled (raises UnsafeSkillError on failure)
                    if self.verify_scripts and skill.scripts:
                        self._verify_script_safety(skill)

                    if skill.name in self._skills:
                        log_warning(f"Duplicate skill name '{skill.name}', overwriting with newer version")
                    self._skills[skill.name] = skill
            except UnsafeSkillError:
                raise  # Don't catch safety errors - let them bubble up
            except Exception as e:
                log_warning(f"Error loading skills from {loader}: {e}")

        self._loaded = True
        log_debug(f"Loaded {len(self._skills)} total skills")

    def _verify_script_safety(self, skill: Skill) -> None:
        """Verify scripts in a skill are safe.

        Raises UnsafeSkillError if potentially malicious code is detected.

        Args:
            skill: The skill to verify.
        """
        if not skill.scripts:
            return

        # If model available, use LLM verification
        if self.verification_model:
            self._verify_with_model(skill)
        else:
            # Fallback: simple heuristic check
            self._verify_with_heuristics(skill)

    def _verify_with_model(self, skill: Skill) -> None:
        """Use LLM to verify script safety.

        Args:
            skill: The skill to verify.

        Raises:
            UnsafeSkillError: If the model detects unsafe code.
        """
        from agno.models.message import Message

        for script in skill.scripts:
            script_name = script.get("name", "unknown")
            script_content = script.get("content", "")

            if not script_content:
                continue

            prompt = f"""You are a security reviewer. Analyze the following script for potential security issues.

Script name: {script_name}
Script content:
```
{script_content}
```

Is this script safe to include in an AI agent skill? Look for:
- Command injection risks (os.system, subprocess with shell=True)
- Destructive file system operations (rm -rf, formatting disks)
- Network exfiltration of sensitive data
- Credential harvesting
- Arbitrary code execution (eval, exec on untrusted input)
- Fork bombs or denial of service patterns
- Obfuscated malicious code

Respond with ONLY "SAFE" or "UNSAFE: <brief reason>"
"""
            try:
                # Create messages for the model
                user_message = Message(role="user", content=prompt)
                assistant_message = Message(role="assistant")

                response = self.verification_model.invoke(
                    messages=[user_message],
                    assistant_message=assistant_message,
                )
                result = response.content.strip() if response.content else ""

                if result.upper().startswith("UNSAFE"):
                    reason = result[7:].strip() if len(result) > 7 else "detected by model"
                    raise UnsafeSkillError(
                        f"Script '{script_name}' in skill '{skill.name}' flagged as unsafe: {reason}"
                    )
            except UnsafeSkillError:
                raise
            except Exception as e:
                # If model verification fails, fall back to heuristics
                log_warning(f"Model verification failed for script '{script_name}': {e}. Falling back to heuristics.")
                self._verify_with_heuristics(skill)
                return  # Heuristics already checked all scripts

    def _verify_with_heuristics(self, skill: Skill) -> None:
        """Simple pattern-based safety check (fallback when no model).

        Uses lenient checks - only blocks very obvious dangerous patterns.

        Args:
            skill: The skill to verify.

        Raises:
            UnsafeSkillError: If dangerous patterns are found.
        """
        # Lenient patterns - only very obviously dangerous code
        dangerous_patterns = [
            ("rm -rf /", "destructive root deletion"),
            ("rm -rf ~", "destructive home deletion"),
            (":(){ :|:& };:", "fork bomb"),
            ("curl | bash", "remote code execution"),
            ("curl | sh", "remote code execution"),
            ("wget | bash", "remote code execution"),
            ("wget | sh", "remote code execution"),
            ("eval(input", "arbitrary code execution from input"),
            ("> /dev/sda", "disk destruction"),
            ("> /dev/hda", "disk destruction"),
            ("mkfs.", "filesystem formatting"),
            ("dd if=/dev/zero", "disk wiping"),
            ("dd if=/dev/random", "disk wiping"),
        ]

        for script in skill.scripts:
            script_name = script.get("name", "unknown")
            content = script.get("content", "")

            for pattern, description in dangerous_patterns:
                if pattern in content:
                    raise UnsafeSkillError(
                        f"Dangerous pattern detected in script '{script_name}' of skill '{skill.name}': "
                        f"'{pattern}' ({description})"
                    )

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name.

        Args:
            name: The name of the skill to retrieve.

        Returns:
            The Skill object if found, None otherwise.
        """
        self._ensure_loaded()
        return self._skills.get(name)

    def get_all_skills(self) -> List[Skill]:
        """Get all loaded skills.

        Returns:
            A list of all loaded Skill objects.
        """
        self._ensure_loaded()
        return list(self._skills.values())

    def get_skill_names(self) -> List[str]:
        """Get the names of all loaded skills.

        Returns:
            A list of skill names.
        """
        self._ensure_loaded()
        return list(self._skills.keys())

    def get_system_prompt_snippet(self) -> str:
        """Generate a system prompt snippet with available skills metadata.

        This creates an XML-formatted snippet that provides the agent with
        information about available skills without including the full instructions.

        Returns:
            An XML-formatted string with skills metadata.
        """
        self._ensure_loaded()

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
            "## Progressive Discovery",
            "Skill information is designed to be loaded on-demand to keep your context focused:",
            "1. **Browse**: Review the skill summaries below to understand what's available",
            "2. **Load**: When a task matches a skill, use `get_skill_instructions` to load full guidance",
            "3. **Reference**: Use `get_skill_reference` to access specific documentation as needed",
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
        self._ensure_loaded()

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

        # Extract names from scripts/references for display
        script_names = [s["name"] if isinstance(s, dict) else s for s in skill.scripts]
        ref_names = [r["name"] if isinstance(r, dict) else r for r in skill.references]

        return json.dumps(
            {
                "skill_name": skill.name,
                "description": skill.description,
                "instructions": skill.instructions,
                "available_scripts": script_names,
                "available_references": ref_names,
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

        # Extract reference names for lookup
        ref_names = [r["name"] if isinstance(r, dict) else r for r in skill.references]

        if reference_path not in ref_names:
            return json.dumps(
                {
                    "error": f"Reference '{reference_path}' not found in skill '{skill_name}'",
                    "available_references": ref_names,
                }
            )

        # First, check if content is stored in the skill (DB-loaded or new format)
        for ref in skill.references:
            if isinstance(ref, dict) and ref.get("name") == reference_path:
                content = ref.get("content", "")
                if content:
                    return json.dumps(
                        {
                            "skill_name": skill_name,
                            "reference_path": reference_path,
                            "content": content,
                        }
                    )
                break

        # Fallback: Get source_path from metadata (for locally loaded skills without content)
        source_path = None
        if skill.metadata:
            source_path = skill.metadata.get("source_path")

        if source_path is None:
            return json.dumps(
                {
                    "error": f"Reference '{reference_path}' has no content stored and skill '{skill_name}' has no source path.",
                    "skill_name": skill_name,
                    "reference_path": reference_path,
                }
            )

        # Load the reference file from filesystem
        ref_file = Path(source_path) / "references" / reference_path
        try:
            content = ref_file.read_text(encoding="utf-8")
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

    def sync_to_db(self, db: "BaseDb") -> int:
        """Sync all loaded skills to a database.

        Args:
            db: The database to sync skills to.

        Returns:
            The count of skills saved to the database.
        """
        self._ensure_loaded()

        if not self._skills:
            log_info("No skills to sync to database")
            return 0

        from agno.skills.loaders.db import DbSkills

        db_loader = DbSkills(db=db)
        count = db_loader.save_all(list(self._skills.values()))
        log_info(f"Synced {count}/{len(self._skills)} skills to database")
        return count

    async def sync_to_db_async(self, db: "AsyncBaseDb") -> int:
        """Sync all loaded skills to a database asynchronously.

        Args:
            db: The async database to sync skills to.

        Returns:
            The count of skills saved to the database.
        """
        self._ensure_loaded()

        if not self._skills:
            log_info("No skills to sync to database")
            return 0

        from agno.skills.loaders.db import DbSkills

        db_loader = DbSkills(db=db)
        count = await db_loader.save_all_async(list(self._skills.values()))
        log_info(f"Synced {count}/{len(self._skills)} skills to database")
        return count

    def get_db_loader(self) -> Optional["DbSkills"]:
        """Get the DbSkills loader if one is configured.

        Returns:
            The DbSkills loader if found, None otherwise.
        """
        from agno.skills.loaders.db import DbSkills

        for loader in self.loaders:
            if isinstance(loader, DbSkills):
                return loader
        return None
