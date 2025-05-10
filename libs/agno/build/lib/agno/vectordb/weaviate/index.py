from enum import Enum


class VectorIndex(Enum):
    HNSW = "hnsw"
    FLAT = "flat"
    DYNAMIC = "dynamic"


class Distance(Enum):
    COSINE = "cosine"
    DOT = "dot"
    L2_SQUARED = "l2-squared"
    HAMMING = "hamming"
    MANHATTAN = "manhattan"
