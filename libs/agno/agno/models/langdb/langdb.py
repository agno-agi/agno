from os import getenv
from typing import Optional
from dataclasses import dataclass
from agno.models.openai.like import OpenAILike


@dataclass
class LangDB(OpenAILike):
    """
    A class for using models hosted on LangDB.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o".
        name (str): The model name. Defaults to "LangDB".
        provider (str): The provider name. Defaults to "LangDB: " + id.
        api_key (Optional[str]): The API key. Defaults to getenv("LANGDB_API_KEY").
        project_id (Optional[str]): The project id. Defaults to None.
    """

    id: str = "gpt-4o"
    name: str = "LangDB"
    provider: str = "LangDB: " + id

    api_key: Optional[str] = getenv("LANGDB_API_KEY")
    project_id: Optional[str] = getenv("LANGDB_PROJECT_ID")
    base_url: str = f"https://api.us-east-1.langdb.ai/{project_id}/v1"
    default_headers: Optional[dict] = None