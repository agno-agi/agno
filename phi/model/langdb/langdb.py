from os import getenv
from typing import Optional

from phi.model.openai.like import OpenAILike


class LangDB(OpenAILike):
    """
    A class for using models hosted on LangDB.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o".
        name (str): The model name. Defaults to "LangDB".
        provider (str): The provider name. Defaults to "LangDB: " + id.
        api_key (Optional[str]): The API key. Defaults to getenv("LANGDB_API_KEY").
        base_url (str): The base URL. Defaults to "https://api.us-east-1.langdb.ai".
    """

    id: str = "gpt-4o"
    name: str = "LangDB"
    provider: str = "LangDB: " + id

    api_key: Optional[str] = getenv("LANGDB_API_KEY")
    base_url: str = "https://api.us-east-1.langdb.ai"
    default_headers: Optional[dict] = None
