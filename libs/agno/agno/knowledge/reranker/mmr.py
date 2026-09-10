from dataclasses import replace
from math import sqrt
from typing import Any, List, Optional, Sequence, Tuple

from pydantic import Field, field_validator

from agno.knowledge.document import Document
from agno.knowledge.reranker.base import Reranker


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity without numpy, which is not a core dependency."""
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (sqrt(left_norm) * sqrt(right_norm))


class MMRReranker(Reranker):
    """Selects results that are relevant to the query but unlike each other.

    Plain vector search returns the closest matches, which are often near-duplicates of
    one another. MMR picks documents one at a time, discounting each candidate by how
    similar it already is to what has been selected.

    Requires an embedding on every candidate document. Verified against live backends:
    pgvector, Qdrant (vector and hybrid), Chroma and LanceDB return them; Milvus,
    MongoDB, Redis, Valkey, Elasticsearch and Qdrant keyword search do not, and MMR
    raises there rather than returning an unreranked list. Pinecone omits vectors unless
    the store is built with return_vectors=True.

    It also needs an embedder to embed the query. Vector dbs that embed queries
    themselves (Upstash hosted embeddings) expose none, so MMR cannot run there.

    The query is embedded with the embedder attached to the search results, so it always
    uses the same model the documents were indexed with.

    Returned documents are shallow copies carrying the MMR score; meta_data and embedding
    are shared with the inputs.

    Do not re-sort the result by reranking_score. Other rerankers score each document
    independently, so their order can be rebuilt from the scores; MMR chooses each
    document against the ones already chosen, so its scores are not descending and
    sorting by them discards the diversity ordering.
    """

    # Weight between relevance and diversity: 1.0 ranks by relevance alone, 0.0 by
    # difference alone.
    lambda_mult: float = Field(default=0.5, ge=0.0, le=1.0)
    # Caps how many documents are selected. Leave unset on Knowledge.reranker, which
    # trims to max_results anyway: a smaller top_n returns fewer documents than asked for.
    top_n: Optional[int] = Field(default=None, gt=0)

    @field_validator("lambda_mult", mode="before")
    @classmethod
    def _reject_bool_lambda(cls, value: Any) -> Any:
        # bool is an int subclass, so True would otherwise coerce to 1.0.
        if isinstance(value, bool):
            raise ValueError("lambda_mult must be a number between 0.0 and 1.0")
        return value

    @field_validator("top_n", mode="before")
    @classmethod
    def _reject_bool_top_n(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("top_n must be a positive integer")
        return value

    def _select(self, query_embedding: Optional[List[float]], documents: List[Document], limit: int) -> List[Document]:
        # Vector dbs return embeddings as lists or as numpy arrays, whose truth value
        # is ambiguous, so length is the portable emptiness check throughout.
        if query_embedding is None or len(query_embedding) == 0:
            raise ValueError("MMRReranker could not embed the query: the embedder returned no vector")

        embeddings: List[List[float]] = [doc.embedding for doc in documents]  # type: ignore[misc]
        # zip() would silently truncate to the shorter vector and score against a prefix.
        dimensions = {len(embedding) for embedding in embeddings} | {len(query_embedding)}
        if len(dimensions) > 1:
            raise ValueError(
                f"MMRReranker requires embeddings of one dimension, but got {sorted(dimensions)}. "
                "The query embedder and the indexed documents likely use different models."
            )

        relevance = [_cosine_similarity(query_embedding, embedding) for embedding in embeddings]

        selected: List[Tuple[int, float]] = []
        remaining = list(range(len(documents)))

        # Seed with the closest match to the query. Scoring the first pick with the MMR
        # formula would tie every candidate at lambda_mult=0.0 and pick by input order.
        first = max(remaining, key=lambda candidate: relevance[candidate])
        selected.append((first, relevance[first]))
        remaining.remove(first)

        # Each candidate's similarity to the nearest selected document, extended as
        # documents are picked. Recomputing it per iteration is quadratic in the number
        # selected, which at the candidate ceiling dominates the search itself.
        best_redundancy = [0.0] * len(documents)
        for candidate in remaining:
            best_redundancy[candidate] = _cosine_similarity(embeddings[candidate], embeddings[first])

        while remaining and len(selected) < limit:
            best_index = remaining[0]
            best_score = float("-inf")
            for candidate in remaining:
                score = self.lambda_mult * relevance[candidate] - (1.0 - self.lambda_mult) * best_redundancy[candidate]
                if score > best_score:
                    best_score = score
                    best_index = candidate
            selected.append((best_index, best_score))
            remaining.remove(best_index)
            for candidate in remaining:
                similarity = _cosine_similarity(embeddings[candidate], embeddings[best_index])
                if similarity > best_redundancy[candidate]:
                    best_redundancy[candidate] = similarity

        results: List[Document] = []
        for index, score in selected:
            # A shallow copy, made only so reranking_score does not land on the caller's
            # documents: meta_data and embedding stay shared with the originals.
            document = replace(documents[index])
            # The MMR score at the moment this document was picked. Unlike a relevance
            # score it is not monotonic across the list, because the candidate pool
            # shrinks as redundancy grows: the returned order is authoritative.
            document.reranking_score = score
            results.append(document)
        return results

    def _prepare(self, documents: List[Document]) -> Optional[int]:
        """Validate inputs and return the number of documents to select."""
        if not documents:
            return None

        # A zero vector is indistinguishable from a broken ingest and would otherwise be
        # selected as maximally different from everything.
        missing = [
            doc.id for doc in documents if doc.embedding is None or len(doc.embedding) == 0 or not any(doc.embedding)
        ]
        if missing:
            # Silently returning the input order would look like MMR ran and found
            # nothing to diversify.
            raise ValueError(
                "MMRReranker requires embeddings on search results, but the vector db returned "
                f"{len(missing)} document(s) without one. Some vector dbs (Milvus, MongoDB, "
                "Redis, Valkey, Elasticsearch) do not return embeddings on search."
            )

        limit = self.top_n if self.top_n is not None else len(documents)
        return min(limit, len(documents))

    def _resolve_embedder(self, documents: List[Document]) -> Any:
        """The embedder travels on the search results, so the query uses the indexing model."""
        for document in documents:
            if document.embedder is not None:
                return document.embedder
        raise ValueError(
            "MMRReranker needs an embedder to embed the query, but the vector db did not "
            "attach one to its search results. Vector dbs that embed queries themselves "
            "(such as Upstash hosted embeddings) do not expose one, so MMR cannot run there."
        )

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        limit = self._prepare(documents)
        if limit is None:
            return documents

        embedder = self._resolve_embedder(documents)
        return self._select(embedder.get_embedding(query), documents, limit)

    async def arerank(self, query: str, documents: List[Document]) -> List[Document]:
        limit = self._prepare(documents)
        if limit is None:
            return documents

        embedder = self._resolve_embedder(documents)
        return self._select(await embedder.async_get_embedding(query), documents, limit)
