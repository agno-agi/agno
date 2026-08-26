from enum import Enum


class SpaceType(str, Enum):
    l2 = "l2"
    cosinesimil = "cosinesimil"
    innerproduct = "innerproduct"


class Engine(str, Enum):
    # nmslib is deprecated and rejected for new index creation from OpenSearch 3.0.0 onwards.
    # It is kept for compatibility with clusters running OpenSearch 2.x.
    nmslib = "nmslib"
    # faiss only supports the cosinesimil space from OpenSearch 2.19 onwards.
    faiss = "faiss"
    lucene = "lucene"
