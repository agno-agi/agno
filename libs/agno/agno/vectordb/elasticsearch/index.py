from enum import Enum


class Similarity(str, Enum):
    """Similarity functions supported by an Elasticsearch dense_vector field."""

    cosine = "cosine"
    l2_norm = "l2_norm"
    dot_product = "dot_product"
    max_inner_product = "max_inner_product"


class HybridStrategy(str, Enum):
    """How a hybrid search combines its vector and keyword halves."""

    # Sum the two scores with the configured boosts. Works on every distribution.
    boost = "boost"
    # Reciprocal rank fusion, which needs no score normalisation but is licensed:
    # basic-licence clusters answer with "current license is non-compliant for [rrf]".
    rrf = "rrf"
