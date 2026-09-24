from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.knowledge.embedder.openai import OpenAIEmbedder


@dataclass
class NebiusEmbedder(OpenAIEmbedder):
    id: str = "Qwen/Qwen3-Embedding-8B"
    dimensions: int = 4096
    api_key: Optional[str] = getenv("NEBIUS_API_KEY")
    base_url: str = "https://api.tokenfactory.nebius.com/v1/"
