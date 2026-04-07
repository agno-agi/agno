from dataclasses import dataclass, field
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class KellyIntelligence(OpenAILike):
    """
    A class for interacting with Kelly Intelligence, an OpenAI-compatible API
    with a built-in 162,000-word vocabulary RAG layer, operated by
    Lesson of the Day, PBC.

    For more information, see: https://api.thedailylesson.com

    Args:
        id (str): The id of the Kelly Intelligence model to use. Defaults to "kelly-haiku".
        name (str): The name of this model. Defaults to "KellyIntelligence".
        provider (str): The provider name. Defaults to "KellyIntelligence".
        base_url (str): The base URL for the Kelly Intelligence API.
            Defaults to "https://api.thedailylesson.com/v1".
        api_key (Optional[str]): The Kelly Intelligence API key. Read from the
            KELLY_API_KEY environment variable when not provided.
    """

    id: str = "kelly-haiku"
    name: str = "KellyIntelligence"
    provider: str = "KellyIntelligence"

    base_url: str = "https://api.thedailylesson.com/v1"
    api_key: Optional[str] = field(default_factory=lambda: getenv("KELLY_API_KEY"))
