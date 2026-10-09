from dataclasses import dataclass
from typing import ClassVar, Optional

from agno.models.decision.base import DecisionModel


@dataclass
class Jev(DecisionModel):
    """TypeSafe's Jev decision model.

    Attributes:
        id (str): The model id. Defaults to "jev-latest".
        api_key (Optional[str]): The API key. Read from TYPESAFE_API_KEY when not set.
        base_url (str): Defaults to "https://api.typesafe.ai".
    """

    id: str = "jev-latest"
    name: str = "Jev"
    provider: Optional[str] = "TypeSafe"

    base_url: Optional[str] = "https://api.typesafe.ai"
    path: str = "/v1/systemone"

    api_key_env: ClassVar[Optional[str]] = "TYPESAFE_API_KEY"
