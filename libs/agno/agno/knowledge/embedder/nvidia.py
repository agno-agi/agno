from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from typing_extensions import Literal

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import logger

try:
    from openai import AsyncOpenAI
    from openai import OpenAI as OpenAIClient
    from openai.types.create_embedding_response import CreateEmbeddingResponse
except ImportError:
    raise ImportError("`openai` not installed")


@dataclass
class NvidiaEmbedder(Embedder):
    id: str = "nvidia/llama-3.2-nemoretriever-1b-vlm-embed-v1"
    dimensions: Optional[int] = None
    encoding_format: Literal["float", "base64"] = "float"
    input_type: Literal["passage", "query"] = "passage"
    user: Optional[str] = None
    api_key: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[str] = "https://integrate.api.nvidia.com/v1"
    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    openai_client: Optional[OpenAIClient] = None
    async_client: Optional[AsyncOpenAI] = None
    
    def __post_init__(self):
        import os
        
        if self.api_key is None:
            self.api_key = os.getenv("NVIDIA_EMBED_API_KEY") or os.getenv("NVIDIA_API_KEY")
        
        if not self.api_key:
            raise ValueError(
                "NVIDIA API key is required. Set NVIDIA_EMBED_API_KEY or "
                "NVIDIA_API_KEY environment variable, or pass api_key parameter."
            )
        
        if self.dimensions is None:
            self.dimensions = 4096 if "nemoretriever" in self.id else 1024
        
        logger.info(f"✅ Initialized NVIDIA Embedder: {self.id}")
        logger.info(f"   Base URL: {self.base_url}")
        logger.info(f"   Input type: {self.input_type}")
        logger.info(f"   Batch processing: {'enabled' if self.batch_size > 1 else 'disabled'}")
    
    @property
    def client(self) -> OpenAIClient:
        if self.openai_client:
            return self.openai_client
        
        _client_params: Dict[str, Any] = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
        }
        _client_params = {k: v for k, v in _client_params.items() if v is not None}
        if self.client_params:
            _client_params.update(self.client_params)
        self.openai_client = OpenAIClient(**_client_params)
        return self.openai_client
    
    @property
    def aclient(self) -> AsyncOpenAI:
        if self.async_client:
            return self.async_client
        
        params = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
        }
        filtered_params: Dict[str, Any] = {k: v for k, v in params.items() if v is not None}
        if self.client_params:
            filtered_params.update(self.client_params)
        self.async_client = AsyncOpenAI(**filtered_params)
        return self.async_client
    
    def response(self, text: str) -> CreateEmbeddingResponse:
        _request_params: Dict[str, Any] = {
            "input": text,
            "model": self.id,
            "encoding_format": self.encoding_format,
        }
        if self.user is not None:
            _request_params["user"] = self.user
        if self.dimensions:
            _request_params["dimensions"] = self.dimensions
        
        if self.input_type:
            _request_params["extra_body"] = {"input_type": self.input_type}
        
        if self.request_params:
            _request_params.update(self.request_params)
        
        return self.client.embeddings.create(**_request_params)
    
    def get_embedding(self, text: str) -> List[float]:
        try:
            response: CreateEmbeddingResponse = self.response(text=text)
            return response.data[0].embedding
        except Exception as e:
            logger.warning(e)
            return []
    
    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            response: CreateEmbeddingResponse = self.response(text=text)
            
            embedding = response.data[0].embedding
            usage = response.usage
            if usage:
                return embedding, usage.model_dump()
            return embedding, None
        except Exception as e:
            logger.warning(e)
            return [], None
    
    async def async_get_embedding(self, text: str) -> List[float]:
        req: Dict[str, Any] = {
            "input": text,
            "model": self.id,
            "encoding_format": self.encoding_format,
        }
        if self.user is not None:
            req["user"] = self.user
        if self.dimensions:
            req["dimensions"] = self.dimensions
        
        if self.input_type:
            req["extra_body"] = {"input_type": self.input_type}
        
        if self.request_params:
            req.update(self.request_params)
        
        try:
            response: CreateEmbeddingResponse = await self.aclient.embeddings.create(**req)
            return response.data[0].embedding
        except Exception as e:
            logger.warning(e)
            return []
    
    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        req: Dict[str, Any] = {
            "input": text,
            "model": self.id,
            "encoding_format": self.encoding_format,
        }
        if self.user is not None:
            req["user"] = self.user
        if self.dimensions:
            req["dimensions"] = self.dimensions
        
        if self.input_type:
            req["extra_body"] = {"input_type": self.input_type}
        
        if self.request_params:
            req.update(self.request_params)
        
        try:
            response = await self.aclient.embeddings.create(**req)
            embedding = response.data[0].embedding
            usage = response.usage
            return embedding, usage.model_dump() if usage else None
        except Exception as e:
            logger.warning(e)
            return [], None
    
    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        all_embeddings = []
        all_usage = []
        logger.info(f"Getting embeddings for {len(texts)} texts in batches of {self.batch_size} (async)")
        
        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]
            
            req: Dict[str, Any] = {
                "input": batch_texts,
                "model": self.id,
                "encoding_format": self.encoding_format,
            }
            if self.user is not None:
                req["user"] = self.user
            if self.dimensions:
                req["dimensions"] = self.dimensions
            
            if self.input_type:
                req["extra_body"] = {"input_type": self.input_type}
            
            if self.request_params:
                req.update(self.request_params)
            
            try:
                response: CreateEmbeddingResponse = await self.aclient.embeddings.create(**req)
                batch_embeddings = [data.embedding for data in response.data]
                all_embeddings.extend(batch_embeddings)
                
                usage_dict = response.usage.model_dump() if response.usage else None
                all_usage.extend([usage_dict] * len(batch_embeddings))
            except Exception as e:
                logger.warning(f"Error in async batch embedding: {e}")
                for text in batch_texts:
                    try:
                        embedding, usage = await self.async_get_embedding_and_usage(text)
                        all_embeddings.append(embedding)
                        all_usage.append(usage)
                    except Exception as e2:
                        logger.warning(f"Error in individual async embedding fallback: {e2}")
                        all_embeddings.append([])
                        all_usage.append(None)
        
        return all_embeddings, all_usage
