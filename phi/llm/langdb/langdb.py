from os import getenv
from typing import Optional, Any

from phi.llm.openai.like import OpenAILike

class LangDB(OpenAILike):
    name: str = "LangDB"
    model: str = "gpt-4o"
    api_key: Optional[str] = getenv("LANGDB_API_KEY")
    base_url: str = "https://api.us-east-1.langdb.ai"
    default_headers: Optional[dict] = None
