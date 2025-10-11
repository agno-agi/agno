from enum import Enum


class SpaceType(str, Enum):
    l2: str = "l2"
    cosinesimil: str = "cosinesimil"
    innerproduct: str = "innerproduct"


class Engine(str, Enum):
    nmslib: str = "nmslib"
    faiss: str = "faiss"
    lucene: str = "lucene"
