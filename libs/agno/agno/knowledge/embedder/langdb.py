from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.knowledge.embedder.openai import OpenAIEmbedder


@dataclass
class LangDBEmbedder(OpenAIEmbedder):
    id: str = "text-embedding-ada-002"
    dimensions: int = 1536
    api_key: Optional[str] = getenv("LANGDB_API_KEY")
    project_id: Optional[str] = getenv("LANGDB_PROJECT_ID")
    base_url: Optional[str] = None

    def __post_init__(self):
        """Set the base_url based on project_id if not provided."""
        if not self.project_id:
            raise ValueError("LANGDB_PROJECT_ID not set in the environment")

        if not self.base_url:
            self.base_url = f"https://api.us-east-1.langdb.ai/{self.project_id}/v1"
