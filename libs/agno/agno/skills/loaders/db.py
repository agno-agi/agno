from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Union

from agno.skills.errors import SkillError, SkillValidationError
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.skills.validator import validate_metadata
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.db.schemas.skills import SkillRow


class DbSkills(SkillLoader):
    """Loads skills from the database's skills table.

    The database-backed sibling of LocalSkills: rows are read in one batched query
    and each becomes a content-carrying Skill via SkillRow.to_skill().

    Args:
        db: Database with the skills methods. A sync backend serves both load()
            and aload(). An async backend is read only by aload(), on the async
            message path; the eager constructor load then starts empty and the
            skills arrive on the first async refresh.
        names: Skill names to load. None (default) loads every row. A name with no
            matching row is skipped with a warning; the rest still load.
        validate: Whether to validate skills against the Agent Skills spec.
            If True (default), invalid skills will raise SkillValidationError.
    """

    refresh_per_request: ClassVar[bool] = True
    owner_scoped: ClassVar[bool] = True

    def __init__(self, db: Union["BaseDb", "AsyncBaseDb"], *, names: Optional[List[str]] = None, validate: bool = True):
        self.db = db
        self.names = names
        self.validate = validate

    def load(self, *, user_id: Optional[str] = None) -> List[Skill]:
        """Load skills from the database.

        Returns:
            A list of Skill objects built from the stored rows.

        Raises:
            SkillError: If the database is async; its skills methods must be awaited,
                so only aload() can read it.
            SkillValidationError: If validation is enabled and a stored skill is invalid,
                or a row's content entries are not string-to-string regardless of validate.
            NotImplementedError: If the database does not implement the skills methods.
        """
        # Imported at the point of use, like SkillRow below: agno.db.base reaches
        # agno.skills through db.schemas, so a module-level import here would cycle.
        from agno.db.base import AsyncBaseDb

        if isinstance(self.db, AsyncBaseDb):
            raise SkillError("DbSkills.load() requires a sync database; use aload() with an async one")
        return self._build_skills(
            self.db.get_skills_with_content(names=self.names, user_id=user_id, include_shared=True)
        )

    async def aload(self, *, user_id: Optional[str] = None) -> List[Skill]:
        """Async twin of load: awaits the skills read when the database is async.

        Returns:
            A list of Skill objects built from the stored rows.

        Raises:
            SkillValidationError: If validation is enabled and a stored skill is invalid,
                or a row's content entries are not string-to-string regardless of validate.
            NotImplementedError: If the database does not implement the skills methods.
        """
        from agno.db.base import AsyncBaseDb

        if not isinstance(self.db, AsyncBaseDb):
            return self.load(user_id=user_id)
        return self._build_skills(
            await self.db.get_skills_with_content(names=self.names, user_id=user_id, include_shared=True)
        )

    def _build_skills(self, rows: List[Dict[str, Any]]) -> List[Skill]:
        """Turn stored rows into Skills, validating each and warning on missing names."""
        # Imported at the point of use: agno.db.schemas.skills imports agno.skills, so a
        # module-level import here would hit that module while it is still initializing.
        from agno.db.schemas.skills import SkillRow

        skills: List[Skill] = []
        for row_data in rows:
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
