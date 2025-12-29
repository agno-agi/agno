"""Database-backed skill loader.

This loader reads skills from a database and can optionally sync skills back to the database.
"""

from typing import List, Optional, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.skills.loaders.base import SkillLoader
from agno.skills.loaders.local import LocalSkills
from agno.skills.skill import Skill
from agno.utils.log import log_debug, log_error, log_info


class DbSkills(SkillLoader):
    """Load skills from a database.

    This loader reads skills from the database and can optionally
    sync skills back to the database.

    Args:
        db: Database instance (sync or async).
        name_filter: Optional name filter to load specific skills.
    """

    def __init__(
        self,
        db: Union[BaseDb, AsyncBaseDb],
        name_filter: Optional[str] = None,
    ):
        self.db = db
        self.name_filter = name_filter

    def load(self) -> List[Skill]:
        """Load skills from database.

        Returns:
            A list of Skill objects loaded from the database.
        """
        if isinstance(self.db, AsyncBaseDb):
            raise RuntimeError(
                "Cannot use synchronous load() with async database. "
                "Use load_async() instead or use a synchronous database."
            )

        try:
            result = self.db.get_skills(name=self.name_filter)
            if isinstance(result, tuple):
                # get_skills returns (skills_list, count) when deserialize=False
                # We always use deserialize=True (default), so cast is safe
                skills = cast(List[Skill], result[0])
            else:
                skills = cast(List[Skill], result)
            log_debug(f"Loaded {len(skills)} skills from database")
            return skills
        except Exception as e:
            log_error(f"Error loading skills from database: {e}")
            return []

    async def load_async(self) -> List[Skill]:
        """Load skills from database asynchronously.

        Returns:
            A list of Skill objects loaded from the database.
        """
        if not isinstance(self.db, AsyncBaseDb):
            raise RuntimeError(
                "Cannot use async load_async() with sync database. Use load() instead or use an async database."
            )

        try:
            result = await self.db.get_skills(name=self.name_filter)
            if isinstance(result, tuple):
                # We always use deserialize=True (default), so cast is safe
                skills = cast(List[Skill], result[0])
            else:
                skills = cast(List[Skill], result)
            log_debug(f"Loaded {len(skills)} skills from database")
            return skills
        except Exception as e:
            log_error(f"Error loading skills from database: {e}")
            return []

    def save(self, skill: Skill) -> Optional[Skill]:
        """Save a skill to the database.

        Args:
            skill: The Skill to save.

        Returns:
            The saved Skill if successful, None otherwise.
        """
        if isinstance(self.db, AsyncBaseDb):
            raise RuntimeError("Cannot use synchronous save() with async database. Use save_async() instead.")

        try:
            result = self.db.upsert_skill(skill)
            if result:
                log_debug(f"Saved skill '{skill.name}' to database")
                # We always use deserialize=True (default), so result is a Skill
                return cast(Skill, result)
            return None
        except Exception as e:
            log_error(f"Error saving skill to database: {e}")
            return None

    async def save_async(self, skill: Skill) -> Optional[Skill]:
        """Save a skill to the database asynchronously.

        Args:
            skill: The Skill to save.

        Returns:
            The saved Skill if successful, None otherwise.
        """
        if not isinstance(self.db, AsyncBaseDb):
            raise RuntimeError("Cannot use async save_async() with sync database. Use save() instead.")

        try:
            result = await self.db.upsert_skill(skill)
            if result:
                log_debug(f"Saved skill '{skill.name}' to database")
                # We always use deserialize=True (default), so result is a Skill
                return cast(Skill, result)
            return None
        except Exception as e:
            log_error(f"Error saving skill to database: {e}")
            return None

    def save_all(self, skills: List[Skill]) -> int:
        """Save multiple skills to database.

        Args:
            skills: The list of Skills to save.

        Returns:
            The count of successfully saved skills.
        """
        if isinstance(self.db, AsyncBaseDb):
            raise RuntimeError("Cannot use synchronous save_all() with async database. Use save_all_async() instead.")

        count = 0
        for skill in skills:
            if self.save(skill):
                count += 1
        log_info(f"Saved {count}/{len(skills)} skills to database")
        return count

    async def save_all_async(self, skills: List[Skill]) -> int:
        """Save multiple skills to database asynchronously.

        Args:
            skills: The list of Skills to save.

        Returns:
            The count of successfully saved skills.
        """
        if not isinstance(self.db, AsyncBaseDb):
            raise RuntimeError("Cannot use async save_all_async() with sync database. Use save_all() instead.")

        count = 0
        for skill in skills:
            if await self.save_async(skill):
                count += 1
        log_info(f"Saved {count}/{len(skills)} skills to database")
        return count

    def delete(self, skill_id: str) -> bool:
        """Delete a skill from database.

        Args:
            skill_id: The ID of the skill to delete.

        Returns:
            True if successful, False otherwise.
        """
        if isinstance(self.db, AsyncBaseDb):
            raise RuntimeError("Cannot use synchronous delete() with async database. Use delete_async() instead.")

        try:
            result = self.db.delete_skill(skill_id)
            if result:
                log_debug(f"Deleted skill with id '{skill_id}' from database")
            return result
        except Exception as e:
            log_error(f"Error deleting skill from database: {e}")
            return False

    async def delete_async(self, skill_id: str) -> bool:
        """Delete a skill from database asynchronously.

        Args:
            skill_id: The ID of the skill to delete.

        Returns:
            True if successful, False otherwise.
        """
        if not isinstance(self.db, AsyncBaseDb):
            raise RuntimeError("Cannot use async delete_async() with sync database. Use delete() instead.")

        try:
            result = await self.db.delete_skill(skill_id)
            if result:
                log_debug(f"Deleted skill with id '{skill_id}' from database")
            return result
        except Exception as e:
            log_error(f"Error deleting skill from database: {e}")
            return False

    @staticmethod
    def load_directory_to_db(
        path: str,
        db: BaseDb,
    ) -> int:
        """Utility: Load skills from directory and persist to DB.

        This is a convenience method to load skills from a local directory
        and save them to the database.

        Args:
            path: Path to the skills directory.
            db: Database instance to save skills to.

        Returns:
            The count of skills saved to the database.
        """
        # Use LocalSkills to load from path
        local_loader = LocalSkills(path)
        skills = local_loader.load()

        if not skills:
            log_info(f"No skills found in {path}")
            return 0

        # Save to DB using DbSkills
        db_loader = DbSkills(db=db)
        count = db_loader.save_all(skills)

        log_info(f"Loaded and saved {count} skills from {path} to database")
        return count

    @staticmethod
    async def load_directory_to_db_async(
        path: str,
        db: AsyncBaseDb,
    ) -> int:
        """Utility: Load skills from directory and persist to DB asynchronously.

        This is a convenience method to load skills from a local directory
        and save them to the database.

        Args:
            path: Path to the skills directory.
            db: Async database instance to save skills to.

        Returns:
            The count of skills saved to the database.
        """
        # Use LocalSkills to load from path
        local_loader = LocalSkills(path)
        skills = local_loader.load()

        if not skills:
            log_info(f"No skills found in {path}")
            return 0

        # Save to DB using DbSkills
        db_loader = DbSkills(db=db)
        count = await db_loader.save_all_async(skills)

        log_info(f"Loaded and saved {count} skills from {path} to database")
        return count
