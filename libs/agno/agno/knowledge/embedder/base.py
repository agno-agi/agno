from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from agno.utils.log import log_error, log_warning


def _is_token_limit_error(error: Exception) -> bool:
    """Check if an exception is related to token limits."""
    error_str = str(error).lower()
    return "maximum context length" in error_str or "token" in error_str


def log_embedding_error(error: Exception, context: str = "embedding") -> None:
    """Log an embedding error with appropriate severity based on error type."""
    if _is_token_limit_error(error):
        log_error(f"Token limit exceeded during {context}: {error}")
    else:
        log_warning(f"Error during {context}: {error}")


@dataclass
class Embedder:
    """Base class for managing embedders"""

    dimensions: Optional[int] = 1536
    enable_batch: bool = False
    batch_size: int = 100  # Number of texts to process in each API call

    def get_embedding(self, text: str) -> List[float]:
        raise NotImplementedError

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    async def async_get_embedding(self, text: str) -> List[float]:
        raise NotImplementedError

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError
