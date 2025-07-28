"""GPUStack Embeddings implementation."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from agno.models.gpustack.base import GPUStackBaseModel
from agno.utils.log import log_debug


@dataclass
class GPUStackEmbeddings(GPUStackBaseModel):
    """GPUStack Embeddings model.

    This class implements the embeddings API for GPUStack,
    supporting text embeddings generation for various use cases.

    API Endpoint: /v1/embeddings
    """

    id: str = "bge-m3"  # Model ID on GPUStack
    name: str = "GPUStackEmbeddings"

    # Request parameters
    encoding_format: Optional[str] = None  # "float" or "base64"
    dimensions: Optional[int] = None

    def _prepare_request(self, input_data: Union[str, List[str]], **kwargs) -> Dict[str, Any]:
        """Prepare request payload for embeddings API."""
        request_data = {
            "model": self.id,
            "input": input_data,
        }

        # Add optional parameters
        if self.encoding_format:
            request_data["encoding_format"] = self.encoding_format
        if self.dimensions:
            request_data["dimensions"] = self.dimensions

        # Override with kwargs
        request_data.update(kwargs)

        return request_data

    def embed(self, texts: Union[str, List[str]], **kwargs) -> Dict[str, Any]:
        """Generate embeddings for text(s)."""
        log_debug(f"GPUStack Embeddings with model: {self.id}")

        request_data = self._prepare_request(input_data=texts, **kwargs)

        response = self._make_request(
            method="POST",
            endpoint="/v1/embeddings",
            json_data=request_data,
        )

        return response.json()

    async def aembed(self, texts: Union[str, List[str]], **kwargs) -> Dict[str, Any]:
        """Generate embeddings for text(s) asynchronously."""
        log_debug(f"GPUStack Embeddings async with model: {self.id}")

        request_data = self._prepare_request(input_data=texts, **kwargs)

        response = await self._amake_request(
            method="POST",
            endpoint="/v1/embeddings",
            json_data=request_data,
        )

        return response.json()

    def parse_embeddings_response(self, response: Dict[str, Any]) -> List[List[float]]:
        """Parse embeddings from response."""
        embeddings = []

        if "data" in response:
            for item in response["data"]:
                if "embedding" in item:
                    embeddings.append(item["embedding"])

        return embeddings
