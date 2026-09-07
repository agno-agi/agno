from dataclasses import dataclass
from typing import Any, Dict, List, NoReturn, Optional, Tuple

from agno.exceptions import EmbeddingError
from agno.utils.log import log_warning


def raise_embedding_error(error: Exception, model_id: Optional[str] = None, provider: Optional[str] = None) -> NoReturn:
    """Re-raise a provider exception as an ``EmbeddingError``, preserving its status code."""
    if isinstance(error, EmbeddingError):
        raise error

    status_code = getattr(error, "status_code", None)
    if not isinstance(status_code, int):
        # Some SDKs expose the HTTP status on a nested response object instead
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int) and isinstance(response, dict):
            # botocore reports it under a response metadata dict
            status_code = response.get("ResponseMetadata", {}).get("HTTPStatusCode")

    raise EmbeddingError(
        f"Failed to generate embedding: {error}",
        # None when the provider reported no HTTP status, so classification falls back to
        # the message text rather than reading a synthesized code as the provider's word.
        status_code=status_code if isinstance(status_code, int) else None,
        model_id=model_id,
        provider=provider,
    ) from error


def first_embedding(entries: Optional[List[Any]], provider: Optional[str] = None) -> Optional[Any]:
    """Return the first entry of an embedding response, or ``None`` when there is none.

    A response carrying no embedding is valid, so it must not surface as an IndexError
    that then gets reported as a provider failure.
    """
    if not entries:
        log_warning(f"{provider or 'Embedder'} returned no embeddings for this request")
        return None
    return entries[0]


def pad_batch_embeddings(
    embeddings: List[List[float]],
    batch_texts: List[str],
    provider: Optional[str] = None,
) -> List[List[float]]:
    """Pad a short batch response so every text keeps its own slot.

    Callers pair embeddings with documents by position, so a response carrying fewer
    embeddings than texts would shift every later text onto the wrong vector. Missing
    entries become empty vectors, which ingestion counts and reports as a shortfall.
    """
    if len(embeddings) >= len(batch_texts):
        return embeddings
    log_warning(
        f"{provider or 'Embedder'} batch response returned {len(embeddings)} of "
        f"{len(batch_texts)} embeddings; the rest are recorded as unembedded"
    )
    return list(embeddings) + [[]] * (len(batch_texts) - len(embeddings))


async def aembed_texts_individually(
    embedder: "Embedder",
    texts: List[str],
) -> Tuple[List[List[float]], List[Optional[Dict]]]:
    """Embed each text on its own, keeping successes and reporting failures once.

    A batch call cannot say which text it choked on, so this per-text pass is the only
    place that knows. Aborting on the first failure would discard every chunk that did
    embed and lose that information, so failures are collected and raised together.
    """
    embeddings: List[List[float]] = []
    usages: List[Optional[Dict]] = []
    failures: List[Tuple[int, EmbeddingError]] = []

    for index, text in enumerate(texts):
        try:
            embedding, usage = await embedder.async_get_embedding_and_usage(text)
        except EmbeddingError as e:
            failures.append((index, e))
            embedding, usage = [], None
        embeddings.append(embedding)
        usages.append(usage)

    if failures:
        first = failures[0][1]
        positions = ", ".join(str(i) for i, _ in failures[:5])
        more = "" if len(failures) <= 5 else f" (and {len(failures) - 5} more)"
        if len(failures) == len(texts):
            # Nothing survived, so there is no partial result worth returning.
            raise EmbeddingError(
                f"All {len(texts)} chunks failed to embed: {first}",
                status_code=first.provider_status_code,
                model_id=first.model_id,
                provider=first.provider,
            )
        # Some chunks embedded. They are returned so they reach the vector store, and
        # the failures are logged with their positions: the caller sees the shortfall as
        # PARTIAL, and the log names which chunks to fix.
        log_warning(f"{len(failures)} of {len(texts)} chunks failed to embed at position(s) {positions}{more}: {first}")

    return embeddings, usages


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
