from pydantic import BaseModel


class SpaceType(BaseModel):
    l2: str = "l2"
    cosinesimil: str = "cosinesimil"
    innerproduct: str = "innerproduct"


class Engine(BaseModel):
    nmslib: str = "nmslib"
    faiss: str = "faiss"
    lucene: str = "lucene"
