"""
Qdrant Hybrid Search with Native Sparse Embeddings
==================================================

Demonstrates Qdrant hybrid retrieval using a custom embedder that provides
native sparse vectors via `get_sparse_embedding()`.

This example shows how to:
1. index documents with dense + native sparse vectors
2. retrieve documents with hybrid search using the same sparse representation

This is useful for embedders such as bge-m3 or any custom embedder that
exposes sparse vectors natively.
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import typer
from agno.agent import Agent
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.knowledge import Knowledge
from agno.models.ollama import Ollama
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType
from rich.prompt import Prompt

try:
    import numpy as np
except ImportError as exc:
    raise ImportError("numpy not installed. Install with: pip install numpy") from exc

try:
    from FlagEmbedding import BGEM3FlagModel
except ImportError as exc:
    raise ImportError(
        "FlagEmbedding not installed. Install with: pip install FlagEmbedding"
    ) from exc


DENSE_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:latest")
COLLECTION_NAME = "thai-recipes-native-sparse"
DOC_URL = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

_bge_model: Optional[BGEM3FlagModel] = None


def get_bge_model() -> BGEM3FlagModel:
    """Lazily initialize the bge-m3 model singleton."""
    global _bge_model
    if _bge_model is None:
        _bge_model = BGEM3FlagModel(DENSE_MODEL, use_fp16=True)
    return _bge_model


@dataclass
class BgeM3Embedder(Embedder):
    """
    Dense + sparse embedder backed by BAAI/bge-m3.

    Required Embedder interface:
    - get_embedding() -> List[float]

    Optional extension detected by Qdrant via duck typing:
    - get_sparse_embedding() -> {"indices": [...], "values": [...]}
    """

    id: str = DENSE_MODEL
    dimensions: int = 1024

    @staticmethod
    def _encode(text: str) -> Dict:
        model = get_bge_model()
        return model.encode(
            [text],
            batch_size=1,
            return_dense=True,
            return_sparse=True,
        )

    def get_embedding(self, text: str) -> List[float]:
        dense_vec = self._encode(text)["dense_vecs"][0]
        return (
            dense_vec.tolist() if isinstance(dense_vec, np.ndarray) else list(dense_vec)
        )

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text), None

    async def async_get_embedding(self, text: str) -> List[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_embedding, text)

    async def async_get_embedding_and_usage(
        self, text: str
    ) -> Tuple[List[float], Optional[Dict]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_embedding_and_usage, text)

    def get_sparse_embedding(self, text: str) -> Dict[str, List]:
        """
        Return sparse lexical weights in Qdrant-compatible format.

        Qdrant will prefer this native sparse representation during hybrid
        indexing and retrieval when `get_sparse_embedding()` is available.
        """
        lexical_weights = self._encode(text)["lexical_weights"][0]
        return {
            "indices": [int(k) for k in lexical_weights.keys()],
            "values": [float(v) for v in lexical_weights.values()],
        }


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

vector_db = Qdrant(
    collection=COLLECTION_NAME,
    url=QDRANT_URL,
    search_type=SearchType.hybrid,
    embedder=BgeM3Embedder(),
)

knowledge = Knowledge(
    name="Qdrant Native Sparse Knowledge Base",
    vector_db=vector_db,
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


def qdrant_agent(user: str = "user") -> None:
    agent = Agent(
        user_id=user,
        knowledge=knowledge,
        search_knowledge=True,
        model=Ollama(id=OLLAMA_MODEL),
        markdown=True,
    )

    while True:
        message = Prompt.ask(f"[bold]{user}[/bold]")
        if message.lower() in {"exit", "bye", "quit"}:
            break
        agent.print_response(message)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------


def main(
    user: str = typer.Option("user", help="User id for the agent session."),
    load_knowledge: bool = typer.Option(
        True,
        "--load-knowledge/--no-load-knowledge",
        help="Load the sample PDF into Qdrant before starting the agent.",
    ),
) -> None:
    if load_knowledge:
        knowledge.insert(
            name="Recipes",
            url=DOC_URL,
            metadata={
                "doc_type": "recipe_book",
                "retrieval": "hybrid_native_sparse",
            },
        )

    qdrant_agent(user=user)


if __name__ == "__main__":
    typer.run(main)
