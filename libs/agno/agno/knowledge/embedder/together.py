from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.knowledge.embedder.openai import OpenAIEmbedder


@dataclass
class TogetherEmbedder(OpenAIEmbedder):
    id: str = "intfloat/multilingual-e5-large-instruct"
    dimensions: int = 1024
    api_key: Optional[str] = getenv("TOGETHER_API_KEY")
    base_url: str = "https://api.together.xyz/v1"
