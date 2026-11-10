from abc import ABC, abstractmethod
from typing import List

from agno.skills.skill import Skill


class SkillLoader(ABC):
    """Abstract base class for skill loaders.

    Skill loaders are responsible for loading skills from various sources
    (local filesystem, GitHub, URLs, etc.) and returning them as Skill objects.

    Subclasses must implement the `load()` method to define how skills
    are loaded from their specific source.
    """

    @abstractmethod
    def load(self) -> List[Skill]:
        """Load skills from the source.

        Returns:
            A list of Skill objects loaded from the source.

        Raises:
            SkillLoadError: If there's an error loading skills from the source.
        """
        pass
