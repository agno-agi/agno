from dataclasses import dataclass
from typing import ClassVar, Optional

from agno.models.decision.base import DecisionModel


@dataclass
class PerplexityDecisions(DecisionModel):
    """Perplexity's Decider decision model, served by the Perplexity Decisions API.

    Attributes:
        id (str): The model id. Defaults to "pplx-decider-v1.1-27b".
        api_key (Optional[str]): The API key. Read from PERPLEXITY_API_KEY when not set.
        base_url (str): Defaults to "https://api.perplexity.ai".
    """

    id: str = "pplx-decider-v1.1-27b"
    name: str = "PerplexityDecisions"
    provider: Optional[str] = "Perplexity"

    base_url: Optional[str] = "https://api.perplexity.ai"
    path: str = "/v1/decisions"

    api_key_env: ClassVar[Optional[str]] = "PERPLEXITY_API_KEY"
