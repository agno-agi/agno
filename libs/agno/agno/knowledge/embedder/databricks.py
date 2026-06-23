from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agno.databricks.async_client import AsyncDatabricksClient
from agno.databricks.client import DatabricksClient
from agno.databricks.settings import DatabricksSettings
from agno.knowledge.embedder.base import Embedder
from agno.utils.log import log_warning


@dataclass
class DatabricksEmbedder(Embedder):
    id: str = "databricks-embedding-endpoint"
    dimensions: Optional[int] = None  # Auto-learned from first API response; set explicitly for create()
    endpoint: Optional[str] = None
    host: Optional[str] = None
    workspace_url: Optional[str] = None
    token: Optional[str] = None
    user: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    default_headers: Optional[Dict[str, str]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    settings: Optional[DatabricksSettings] = None
    client: Optional[DatabricksClient] = None
    async_client: Optional[AsyncDatabricksClient] = None

    def __post_init__(self):
        if self.endpoint is None:
            self.endpoint = self.id

    def _get_settings(self) -> DatabricksSettings:
        overrides: Dict[str, Any] = {}
        if self.host is not None:
            overrides["host"] = self.host
            if self.workspace_url is None:
                overrides["workspace_url"] = self.host
        if self.workspace_url is not None:
            overrides["workspace_url"] = self.workspace_url
        if self.token is not None:
            overrides["token"] = self.token
        if self.timeout is not None:
            overrides["timeout"] = self.timeout
        if self.max_retries is not None:
            overrides["max_retries"] = self.max_retries
        if self.default_headers is not None:
            overrides["default_headers"] = self.default_headers

        if self.settings is None:
            if overrides:
                self.settings = DatabricksSettings.from_values(**overrides)
            else:
                self.settings = DatabricksSettings()
        elif overrides:
            self.settings = self.settings.with_overrides(**overrides)

        return self.settings

    def get_client(self) -> DatabricksClient:
        if self.client is None:
            self.client = DatabricksClient(
                settings=self._get_settings(),
            )
        return self.client

    def get_async_client(self) -> AsyncDatabricksClient:
        if self.async_client is None:
            self.async_client = AsyncDatabricksClient(
                settings=self._get_settings(),
            )
        return self.async_client

    def _build_request_params(self, text: str) -> Dict[str, Any]:
        request_params: Dict[str, Any] = {
            "model": self.endpoint or self.id,
            "input": [text],
        }
        if self.dimensions is not None:
            request_params["dimensions"] = self.dimensions
        if self.user is not None:
            request_params["user"] = self.user
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def _build_batch_request_params(self, texts: List[str]) -> Dict[str, Any]:
        request_params: Dict[str, Any] = {
            "model": self.endpoint or self.id,
            "input": texts,
        }
        if self.dimensions is not None:
            request_params["dimensions"] = self.dimensions
        if self.user is not None:
            request_params["user"] = self.user
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def _extract_embeddings(self, response: Dict[str, Any]) -> List[List[float]]:
        data = response.get("data") or []
        sorted_data = sorted(
            (item for item in data if isinstance(item, dict)),
            key=lambda item: item.get("index", 0),
        )
        embeddings: List[List[float]] = []
        for item in sorted_data:
            embedding = item.get("embedding")
            if isinstance(embedding, list):
                embeddings.append(embedding)
        return embeddings

    def _update_dimensions_from_embeddings(self, embeddings: List[List[float]]) -> None:
        if self.dimensions is None and embeddings:
            self.dimensions = len(embeddings[0])

    def _extract_usage(self, response: Dict[str, Any]) -> Optional[Dict]:
        usage = response.get("usage")
        return usage if isinstance(usage, dict) else None

    def _response(self, text: str) -> Any:
        return self.get_client().request_json(
            "POST",
            "/serving-endpoints/embeddings",
            json=self._build_request_params(text),
        )

    async def _async_response(self, text: str) -> Any:
        return await self.get_async_client().request_json(
            "POST",
            "/serving-endpoints/embeddings",
            json=self._build_request_params(text),
        )

    def get_embedding(self, text: str) -> List[float]:
        try:
            response = self._response(text)
            embeddings = self._extract_embeddings(response)
            self._update_dimensions_from_embeddings(embeddings)
            return embeddings[0] if embeddings else []
        except Exception as e:
            log_warning(f"Failed to get embedding: {str(e)}")
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            response = self._response(text)
            embeddings = self._extract_embeddings(response)
            self._update_dimensions_from_embeddings(embeddings)
            return (embeddings[0] if embeddings else []), self._extract_usage(response)
        except Exception as e:
            log_warning(f"Failed to get embedding and usage: {str(e)}")
            return [], None

    async def async_get_embedding(self, text: str) -> List[float]:
        try:
            response = await self._async_response(text)
            embeddings = self._extract_embeddings(response)
            self._update_dimensions_from_embeddings(embeddings)
            return embeddings[0] if embeddings else []
        except Exception as e:
            log_warning(f"Failed to get async embedding: {str(e)}")
            return []

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            response = await self._async_response(text)
            embeddings = self._extract_embeddings(response)
            self._update_dimensions_from_embeddings(embeddings)
            return (embeddings[0] if embeddings else []), self._extract_usage(response)
        except Exception as e:
            log_warning(f"Failed to get async embedding and usage: {str(e)}")
            return [], None

    def get_embeddings_batch_and_usage(self, texts: List[str]) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        all_embeddings: List[List[float]] = []
        all_usage: List[Optional[Dict]] = []

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]
            try:
                response = self.get_client().request_json(
                    "POST",
                    "/serving-endpoints/embeddings",
                    json=self._build_batch_request_params(batch_texts),
                )
                batch_embeddings = self._extract_embeddings(response)
                self._update_dimensions_from_embeddings(batch_embeddings)
                usage = self._extract_usage(response)
                all_embeddings.extend(batch_embeddings)
                all_usage.extend([usage] * len(batch_embeddings))
            except Exception as e:
                log_warning(f"Error in batch embedding: {str(e)}")
                for text in batch_texts:
                    embedding, usage = self.get_embedding_and_usage(text)
                    all_embeddings.append(embedding)
                    all_usage.append(usage)

        return all_embeddings, all_usage

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        all_embeddings: List[List[float]] = []
        all_usage: List[Optional[Dict]] = []

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]
            try:
                response = await self.get_async_client().request_json(
                    "POST",
                    "/serving-endpoints/embeddings",
                    json=self._build_batch_request_params(batch_texts),
                )
                batch_embeddings = self._extract_embeddings(response)
                self._update_dimensions_from_embeddings(batch_embeddings)
                usage = self._extract_usage(response)
                all_embeddings.extend(batch_embeddings)
                all_usage.extend([usage] * len(batch_embeddings))
            except Exception as e:
                log_warning(f"Error in async batch embedding: {str(e)}")
                for text in batch_texts:
                    embedding, usage = await self.async_get_embedding_and_usage(text)
                    all_embeddings.append(embedding)
                    all_usage.append(usage)

        return all_embeddings, all_usage
