from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.models.openai.like import OpenAILike
from agno.utils.log import logger


@dataclass
class LangDB(OpenAILike):
    """
    A class for using models hosted on LangDB.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o".
        name (str): The model name. Defaults to "LangDB".
        provider (str): The provider name. Defaults to "LangDB".
        api_key (Optional[str]): The API key. Defaults to getenv("LANGDB_API_KEY").
        project_id (Optional[str]): The project id. Defaults to None.
    """

    id: str = "gpt-4o"
    name: str = "LangDB"
    provider: str = "LangDB"

    api_key: Optional[str] = getenv("LANGDB_API_KEY")
    project_id: Optional[str] = getenv("LANGDB_PROJECT_ID")
    if not project_id:
        logger.warning("LANGDB_PROJECT_ID not set in the environment")
    base_url: str = f"https://api.us-east-1.langdb.ai/{project_id}/v1"
    label: Optional[str] = None
    default_headers: Optional[dict] = None

    def _get_client_params(self) -> Dict[str, Any]:
        # Initialize headers with label if present
        if self.label and not self.default_headers:
            self.default_headers = {
                "x-label": self.label,
            }
        client_params = super()._get_client_params()

        return client_params
