from os import getenv
from typing import Optional

from phi.llm.openai.like import OpenAILike


class LangDB(OpenAILike):
    name: str = "LangDB"
    model: str = "gpt-4o"
    api_key: Optional[str] = getenv("LANGDB_API_KEY")
    base_url: str = "https://api.us-east-1.langdb.ai"
    project_id: Optional[str] = None
    default_headers: Optional[dict] = None

    def __init__(self, project_id: Optional[str] = None) -> None:
        super().__init__()
        self.project_id = project_id
        if self.project_id:
            self.base_url = f"https://api.us-east-1.langdb.ai/{self.project_id}/v1"
