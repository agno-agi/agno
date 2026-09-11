"""MMR reranking: diversity selection, configuration and embedding requirements."""

from typing import List, Optional

import pytest

from agno.knowledge.document import Document
from agno.knowledge.reranker.mmr import MMRReranker, _cosine_similarity


class StubEmbedder:
    """Returns a fixed query embedding without calling a provider."""

    def __init__(self, embedding: Optional[List[float]] = None):
        self.embedding = [1.0, 0.0] if embedding is None else embedding

    def get_embedding(self, text: str) -> List[float]:
        return self.embedding

    async def async_get_embedding(self, text: str) -> List[float]:
        return self.embedding


def _documents() -> List[Document]:
    """Two near-duplicates, then a document that is less relevant but far from them.

    Relevance alone ranks a > b > c. Selecting "a" first makes "b" redundant, so an
    even relevance/diversity split prefers "c" despite its lower relevance.
    """
    embedder = StubEmbedder()
    return [
        Document(id="a", content="a", embedding=[1.0, 0.5], embedder=embedder),
        Document(id="b", content="b", embedding=[1.0, 0.55], embedder=embedder),
        Document(id="c", content="c", embedding=[1.0, -0.7], embedder=embedder),
    ]


def test_cosine_similarity_of_identical_vectors_is_one():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_of_orthogonal_vectors_is_zero():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_zero_vector_does_not_divide_by_zero():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_diversity_beats_the_near_duplicate():
    results = MMRReranker(lambda_mult=0.5, top_n=2).rerank("q", _documents())

    # "b" is the closer match, but it nearly duplicates "a", so the distinct doc wins.
    assert [doc.id for doc in results] == ["a", "c"]


def test_pure_relevance_keeps_the_near_duplicate():
    results = MMRReranker(lambda_mult=1.0, top_n=2).rerank("q", _documents())

    assert [doc.id for doc in results] == ["a", "b"]


def test_reranking_score_is_the_score_at_selection_time():
    # MMR scores are not descending: the pool shrinks as redundancy grows, so a later
    # pick can score above an earlier one. List order, not score order, is the result.
    embedder = StubEmbedder()
    documents = [
        Document(id="a", content="a", embedding=[-1.0, 0.0], embedder=embedder),
        Document(id="b", content="b", embedding=[-0.9, 0.44], embedder=embedder),
        Document(id="c", content="c", embedding=[-0.9, -0.44], embedder=embedder),
    ]

    results = MMRReranker(lambda_mult=0.5).rerank("q", documents)

    scores = [doc.reranking_score for doc in results]
    assert scores != sorted(scores, reverse=True)
    assert [doc.id for doc in results] == ["b", "c", "a"]


def test_top_n_defaults_to_all_documents():
    results = MMRReranker().rerank("q", _documents())

    assert len(results) == 3


def test_top_n_larger_than_input_is_clamped():
    results = MMRReranker(top_n=10).rerank("q", _documents())

    assert len(results) == 3


def test_empty_documents_returns_empty():
    assert MMRReranker().rerank("q", []) == []


def test_missing_embeddings_raise_rather_than_silently_passing_through():
    documents = _documents()
    documents[1].embedding = None

    with pytest.raises(ValueError, match="requires embeddings"):
        MMRReranker().rerank("q", documents)


def test_missing_embedder_raises():
    documents = _documents()
    for document in documents:
        document.embedder = None

    with pytest.raises(ValueError, match="needs an embedder"):
        MMRReranker().rerank("q", documents)


def test_embedder_is_taken_from_any_result_that_has_one():
    documents = _documents()
    documents[0].embedder = None

    results = MMRReranker(lambda_mult=0.5, top_n=2).rerank("q", documents)

    assert [doc.id for doc in results] == ["a", "c"]


@pytest.mark.asyncio
async def test_arerank_matches_sync_selection():
    results = await MMRReranker(lambda_mult=0.5, top_n=2).arerank("q", _documents())

    assert [doc.id for doc in results] == ["a", "c"]


def test_mismatched_embedding_dimensions_raise():
    documents = _documents()
    documents[1].embedding = [1.0, 0.5, 0.25]

    with pytest.raises(ValueError, match="one dimension"):
        MMRReranker().rerank("q", documents)


def test_query_embedding_of_wrong_dimension_raises():
    documents = _documents()
    for document in documents:
        document.embedder = StubEmbedder(embedding=[1.0, 0.0, 0.0])

    with pytest.raises(ValueError, match="one dimension"):
        MMRReranker().rerank("q", documents)


def test_embedder_returning_no_vector_raises():
    documents = _documents()
    for document in documents:
        document.embedder = StubEmbedder(embedding=[])

    with pytest.raises(ValueError, match="could not embed the query"):
        MMRReranker().rerank("q", documents)


def test_numpy_embeddings_are_supported():
    # PgVector returns embeddings as numpy arrays, whose truth value is ambiguous.
    numpy = pytest.importorskip("numpy")

    embedder = StubEmbedder(embedding=numpy.array([1.0, 0.0]))
    documents = [
        Document(id="a", content="a", embedding=numpy.array([1.0, 0.5]), embedder=embedder),
        Document(id="b", content="b", embedding=numpy.array([1.0, 0.55]), embedder=embedder),
        Document(id="c", content="c", embedding=numpy.array([1.0, -0.7]), embedder=embedder),
    ]

    results = MMRReranker(lambda_mult=0.5, top_n=2).rerank("q", documents)

    assert [doc.id for doc in results] == ["a", "c"]


@pytest.mark.parametrize("kwargs", [{"lambda_mult": True}, {"top_n": True}])
def test_booleans_are_rejected_as_numeric_config(kwargs):
    # bool is an int subclass, so True would otherwise coerce to 1.0 / 1.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MMRReranker(**kwargs)


def test_named_vector_mapping_is_not_treated_as_an_embedding():
    # Qdrant hybrid/keyword searches return a dict of named vectors.
    documents = _documents()
    documents[1].embedding = {"dense": [1.0, 0.55]}  # type: ignore[assignment]

    with pytest.raises(ValueError, match="one dimension"):
        MMRReranker().rerank("q", documents)


def test_reranking_score_is_the_mmr_score_not_a_rank_ordinal():
    results = MMRReranker(lambda_mult=0.5, top_n=2).rerank("q", _documents())

    # Rank ordinals would be 2.0 and 1.0; real MMR scores are bounded by lambda_mult.
    scores = [doc.reranking_score for doc in results]
    assert all(score <= 1.0 for score in scores)


def test_input_documents_are_not_scored_in_place():
    documents = _documents()

    MMRReranker(lambda_mult=0.5, top_n=2).rerank("q", documents)

    assert all(document.reranking_score is None for document in documents)


def test_zero_vector_is_rejected_as_a_broken_embedding():
    documents = _documents()
    documents[1].embedding = [0.0, 0.0]

    with pytest.raises(ValueError, match="requires embeddings"):
        MMRReranker().rerank("q", documents)


@pytest.mark.parametrize("kwargs", [{"lambda_mult": -0.1}, {"lambda_mult": 1.1}, {"top_n": 0}, {"top_n": -1}])
def test_out_of_range_config_is_rejected_at_construction(kwargs):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MMRReranker(**kwargs)


def test_pure_diversity_does_not_depend_on_input_order():
    # At lambda_mult=0.0 every candidate ties on the first pick, so the seed cannot be
    # scored with the MMR formula or the input order decides the whole selection.
    import itertools

    embeddings = {"a": [1.0, 0.1], "b": [1.0, 0.5], "c": [1.0, -0.9]}

    def documents(order):
        embedder = StubEmbedder()
        return [Document(id=key, content=key, embedding=embeddings[key], embedder=embedder) for key in order]

    selections = {
        tuple(doc.id for doc in MMRReranker(lambda_mult=0.0, top_n=2).rerank("q", documents(list(order))))
        for order in itertools.permutations("abc")
    }

    assert len(selections) == 1


def test_selection_matches_the_unoptimised_formula():
    # Pins the running-redundancy optimisation to the definition it replaced.
    import random

    from agno.knowledge.reranker.mmr import _cosine_similarity

    def reference(query_embedding, documents, lambda_mult, limit):
        embeddings = [doc.embedding for doc in documents]
        relevance = [_cosine_similarity(query_embedding, embedding) for embedding in embeddings]
        remaining = list(range(len(documents)))
        first = max(remaining, key=lambda candidate: relevance[candidate])
        selected = [first]
        remaining.remove(first)
        while remaining and len(selected) < limit:
            best_index, best_score = remaining[0], float("-inf")
            for candidate in remaining:
                redundancy = max(_cosine_similarity(embeddings[candidate], embeddings[j]) for j in selected)
                score = lambda_mult * relevance[candidate] - (1.0 - lambda_mult) * redundancy
                if score > best_score:
                    best_score, best_index = score, candidate
            selected.append(best_index)
            remaining.remove(best_index)
        return [documents[i].id for i in selected]

    query_embedding = [1.0] + [0.0] * 15

    def build(seed):
        rnd = random.Random(seed)
        embedder = StubEmbedder(embedding=query_embedding)
        return [
            Document(
                id=str(i),
                content=str(i),
                embedding=[rnd.uniform(-1, 1) for _ in range(16)],
                embedder=embedder,
            )
            for i in range(30)
        ]

    for seed in range(5):
        for lambda_mult in (0.0, 0.5, 1.0):
            selected = [doc.id for doc in MMRReranker(lambda_mult=lambda_mult, top_n=8).rerank("q", build(seed))]
            assert selected == reference(query_embedding, build(seed), lambda_mult, 8)
