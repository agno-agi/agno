import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.tools.function import Function
from agno.utils.log import log_debug, log_info, log_warning

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb


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

    def __init__(self, loaders: List[SkillLoader], dynamic: bool = True):
        """Initialize Skills orchestrator.

        Args:
            loaders: List of SkillLoader instances to load skills from.
            dynamic: If True (default), reload skills from loaders on every access.
                     Useful for DB-backed skills that may change at runtime.
        """
        self.loaders = loaders
        self.dynamic = dynamic
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
                    if skill.name in self._skills:
                        log_warning(f"Duplicate skill name '{skill.name}', overwriting with newer version")
                    self._skills[skill.name] = skill
            except Exception as e:
                log_warning(f"Error loading skills from {loader}: {e}")

        self._loaded = True
        log_debug(f"Loaded {len(self._skills)} total skills")

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

        lines = ["<available_skills>"]
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
        lines.append("</available_skills>")
        lines.append("")
        lines.append(
            "You have access to skills that provide domain expertise. Use the get_skill_instructions tool "
            "to load full instructions when you need to use a skill. Use get_skill_reference to access "
            "detailed documentation from reference files."
        )

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
