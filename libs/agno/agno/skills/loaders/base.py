from abc import ABC, abstractmethod
from typing import ClassVar, List, Optional

from agno.skills.skill import Skill


class SkillLoader(ABC):
    """Abstract base class for skill loaders.

    Skill loaders are responsible for loading skills from various sources
    (local filesystem, GitHub, URLs, etc.) and returning them as Skill objects.

    Subclasses must implement the `load()` method to define how skills
    are loaded from their specific source.
    """

    # True for a source that changes between requests (the database): re-run per system prompt.
    refresh_per_request: ClassVar[bool] = False

    # True for a source with owners: load()/aload() receive the run's user_id. Left False,
    # the loader is called with no arguments, as before this existed.
    owner_scoped: ClassVar[bool] = False

    @abstractmethod
    def load(self, *, user_id: Optional[str] = None) -> List[Skill]:
        """Load skills from the source.

        Args:
            user_id: The user the skills are loaded for, when the source has owners.

        Returns:
            A list of Skill objects loaded from the source.

        Raises:
            SkillLoadError: If there's an error loading skills from the source.
        """
        pass

    async def aload(self, *, user_id: Optional[str] = None) -> List[Skill]:
        """Async twin of load. Loaders whose source has async methods override this;
        the default delegates to the sync load.
        """
        return self.load(user_id=user_id) if self.owner_scoped else self.load()
