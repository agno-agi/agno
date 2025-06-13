from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.embedder.openai import OpenAIEmbedder


@dataclass
class NebiusEmbedder(OpenAIEmbedder):
    id: str = "BAAI/bge-en-icl"
    dimensions: int = 1024
    api_key: Optional[str] = getenv("NEBIUS_API_KEY")
    base_url: str = "https://api.studio.nebius.com/v1/"
