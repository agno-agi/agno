from abc import ABC, abstractmethod
from typing import ClassVar, List

from agno.skills.skill import Skill


class SkillLoader(ABC):
    """Abstract base class for skill loaders.

    Skill loaders are responsible for loading skills from various sources
    (local filesystem, GitHub, URLs, etc.) and returning them as Skill objects.

    Subclasses must implement the `load()` method to define how skills
    are loaded from their specific source.
    """

    # Loaders reading a source that can change between requests (the database) declare
    # True, and Skills re-runs them each time a system prompt is built.
    refresh_per_request: ClassVar[bool] = False

    @abstractmethod
    def load(self) -> List[Skill]:
        """Load skills from the source.

        Returns:
            A list of Skill objects loaded from the source.

        Raises:
            SkillLoadError: If there's an error loading skills from the source.
        """
        pass

    async def aload(self) -> List[Skill]:
        """Async twin of load. Loaders whose source has async methods override this;
        the default delegates to the sync load.
        """
        return self.load()
