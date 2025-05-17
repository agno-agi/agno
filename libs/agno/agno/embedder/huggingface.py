import json
from dataclasses import dataclass
from os import getenv
from packaging import version
from typing import Any, Dict, List, Optional, Tuple

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    from huggingface_hub import InferenceClient, __version__
except ImportError:
    logger.error("`huggingface-hub` not installed, please run `pip install huggingface-hub`")
    raise


@dataclass
class HuggingfaceCustomEmbedder(Embedder):
    """Huggingface Custom Embedder"""

    id: str = "jinaai/jina-embeddings-v2-base-code"
    api_key: Optional[str] = getenv("HUGGINGFACE_API_KEY")
    task: str = "feature-extraction"
    client_params: Optional[Dict[str, Any]] = None
    huggingface_client: Optional[InferenceClient] = None

    @property
    def client(self) -> InferenceClient:
        if self.huggingface_client:
            return self.huggingface_client
        _client_params: Dict[str, Any] = {}
        if self.api_key:
            _client_params["api_key"] = self.api_key
        if self.client_params:
            _client_params.update(self.client_params)
        self.huggingface_client = InferenceClient(**_client_params)
        return self.huggingface_client

    def _response_v1(self, text: str):
        return self.client.post(json={"inputs": text}, model=self.id, task=self.task)

    def _response_v2(self, text: str):
        return self.client.feature_extraction(text=text, model=self.id)

    def get_embedding(self, text: str) -> List[float]:
        if version.parse(__version__) <= version.parse("0.30.2"):
            response = self._response_v1(text=text)
            try:
                decoded_string = response.decode("utf-8")
                return json.loads(decoded_string)

            except Exception as e:
                logger.warning(e)
                return []
        else:  # version huggingface_hub > 0.30.2
            try:
                return self._response_v2(text=text)
            except Exception as e:
                logger.warning(e)
                return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text=text), None
