from typing import Optional

from pydantic import BaseModel


class HNSW(BaseModel):
    name: Optional[str] = None
    m: int = 16
    ef_construct: int = 200
