from dataclasses import dataclass
from os import getenv
from typing import Dict, List, Optional, Tuple

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    import dashscope
except ImportError:
    logger.error("`dashscope` not installed, please run `pip install dashscope`")
    raise

@dataclass
class DashscopeEmbedder(Embedder):
    id: str = "text-embedding-v3"
    api_key: Optional[str] = getenv("DASHSCOPE_API_KEY")
    ds_text_type: Optional[str] = "query"
    ds_output_type: Optional[str] = "dense&sparse"

    ds_model_mapping = {
        'text-embedding-v1': dashscope.TextEmbedding.Models.text_embedding_v1,
        'text-embedding-v2': dashscope.TextEmbedding.Models.text_embedding_v2,
        'text-embedding-v3': dashscope.TextEmbedding.Models.text_embedding_v3,
    }

    @property
    def client(self) -> dashscope:
        if self.api_key:
            dashscope.api_key = self.api_key
        self.dashscope_client = dashscope
        return self.dashscope_client

    def _response(self, text: str):
        model = self.ds_model_mapping.get(self.id)
        if model is None:
            raise ValueError(f"Unsupported dashscope model version: {self.id}")
        return self.client.TextEmbedding.call(
            model=model,
            input=text,
            text_type=self.ds_text_type,
            output_type=self.ds_output_type
        )
    
    def get_embedding(self, text: str) -> List[float]:
        response = self._response(text=text)
        try:
            resp = response.output['embeddings'][0]['embedding']
            print(resp)
            return resp
        except Exception as e:
            logger.warning(e)
            return []
    
    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text=text), None