from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.embedder.openai import OpenAIEmbedder


@dataclass
class FireworksEmbedder(OpenAIEmbedder):
    id: str = "nomic-ai/nomic-embed-text-v1.5"
    dimensions: int = 768
    api_key: Optional[str] = getenv("FIREWORKS_API_KEY")
    base_url: str = "https://api.fireworks.ai/inference/v1"
