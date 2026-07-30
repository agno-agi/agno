from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional

from agno.skills.errors import SkillValidationError
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.skills.validator import validate_metadata
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.db.schemas.skills import SkillRow


class DbSkills(SkillLoader):
    """Loads skills from the database's skills table.

    The database-backed sibling of LocalSkills: rows are read in one batched query
    and each becomes a content-carrying Skill via SkillRow.to_skill().

    Args:
        db: Database with the skills methods. The loader path is sync, so this is
            a sync backend handle.
        names: Skill names to load. None (default) loads every row. A name with no
            matching row is skipped with a warning; the rest still load.
        validate: Whether to validate skills against the Agent Skills spec.
            If True (default), invalid skills will raise SkillValidationError.
    """

    refresh_per_request: ClassVar[bool] = True

    def __init__(self, db: "BaseDb", *, names: Optional[List[str]] = None, validate: bool = True):
        self.db = db
        self.names = names
        self.validate = validate

    def load(self) -> List[Skill]:
        """Load skills from the database.

        Returns:
            A list of Skill objects built from the stored rows.

        Raises:
            SkillValidationError: If validation is enabled and a stored skill is invalid,
                or a row's content entries are not string-to-string regardless of validate.
            NotImplementedError: If the database does not implement the skills methods.
        """
        # Imported at the point of use: agno.db.schemas.skills imports agno.skills, so a
        # module-level import here would hit that module while it is still initializing.
        from agno.db.schemas.skills import SkillRow

        skills: List[Skill] = []
        for row_data in self.db.get_skills_with_content(names=self.names):
            row = SkillRow.from_dict(row_data)
            if self.validate:
                errors = validate_metadata(self._row_metadata(row))
                if errors:
                    raise SkillValidationError(
                        f"Skill validation failed for '{row.name}'",
                        errors=errors,
                    )
            skills.append(row.to_skill())

        if self.names:
            for name in sorted(set(self.names) - {skill.name for skill in skills}):
                log_warning(f"Skill '{name}' has no row in the skills table, skipping")

        log_debug(f"Loaded {len(skills)} skills from the database")
        return skills

    def _row_metadata(self, row: "SkillRow") -> Dict[str, Any]:
        """Shape a row's descriptive fields like SKILL.md frontmatter for validate_metadata."""
        fields = {
            "name": row.name,
            "description": row.description,
            "license": row.license,
            "compatibility": row.compatibility,
            "allowed-tools": row.allowed_tools,
            "metadata": row.metadata,
        }
        # Unset optionals are omitted, not passed as None: the validator checks presence.
        return {key: value for key, value in fields.items() if value is not None}
