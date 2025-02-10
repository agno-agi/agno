from typing import Literal

from pydantic import BaseModel


class HNSW(BaseModel):
    quantization: Literal["f64", "f32", "f16", "bf16", "i8"] = "bf16"
    hnsw_max_connections_per_layer: int = 32
    hnsw_candidate_list_size_for_construction: int = 128
