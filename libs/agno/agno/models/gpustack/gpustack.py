"""Unified GPUStack model implementation."""

from dataclasses import dataclass
from typing import Literal, Optional

from agno.models.gpustack.chat import GPUStackChat
from agno.models.gpustack.embeddings import GPUStackEmbeddings
from agno.models.gpustack.rerank import GPUStackRerank
from agno.utils.log import log_error


@dataclass
class GPUStack:
    """Unified GPUStack model factory.

    This class provides a convenient way to create GPUStack models
    for different tasks using a single interface.

    Example:
        ```python
        # Create a chat model
        chat_model = GPUStack(
            model_type="chat",
            id="llama3",
            base_url="http://localhost:9009",
            api_key="your-api-key"
        )

        # Create an embeddings model
        embeddings_model = GPUStack(
            model_type="embeddings",
            id="bge-m3"
        )

        # Create a rerank model
        rerank_model = GPUStack(
            model_type="rerank",
            id="bge-reranker-v2-m3"
        )
        ```
    """

    model_type: Literal["chat", "embeddings", "rerank"] = "chat"

    id: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None

    def __new__(cls, **kwargs):
        """Create the appropriate GPUStack model based on model_type."""
        model_type = kwargs.pop("model_type", "chat")

        # Map model types to classes
        model_classes = {
            "chat": GPUStackChat,
            "embeddings": GPUStackEmbeddings,
            "rerank": GPUStackRerank,
        }

        model_class = model_classes.get(model_type)
        if not model_class:
            log_error(f"Unknown model type: {model_type}")
            raise ValueError(f"Invalid model_type: {model_type}. Must be one of: {list(model_classes.keys())}")

        # Create and return the specific model instance
        return model_class(**kwargs)
