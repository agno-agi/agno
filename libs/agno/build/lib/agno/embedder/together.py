from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.embedder.openai import OpenAIEmbedder


@dataclass
class TogetherEmbedder(OpenAIEmbedder):
    id: str = "togethercomputer/m2-bert-80M-32k-retrieval"
    dimensions: int = 768
    api_key: Optional[str] = getenv("TOGETHER_API_KEY")
    base_url: str = "https://api.together.xyz/v1"
