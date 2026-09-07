from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from agno.knowledge.embedder.base import (
    Embedder,
    aembed_texts_individually,
    pad_batch_embeddings,
    raise_embedding_error,
)
from agno.utils.gemini import inject_agno_client_header
from agno.utils.log import log_error, log_info, log_warning

try:
    from google import genai
    from google.genai import Client as GeminiClient
    from google.genai.types import EmbedContentResponse
except ImportError:
    raise ImportError("`google-genai` not installed. Please install it using `pip install google-genai`")


@dataclass
class GeminiEmbedder(Embedder):
    id: str = "gemini-embedding-001"
    task_type: str = "RETRIEVAL_QUERY"
    title: Optional[str] = None
    dimensions: Optional[int] = 1536
    api_key: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    gemini_client: Optional[GeminiClient] = None
    # Vertex AI parameters
    vertexai: bool = False
    project_id: Optional[str] = None
    location: Optional[str] = None

    @property
    def client(self):
        if self.gemini_client:
            return self.gemini_client

        _client_params: Dict[str, Any] = {}
        vertexai = self.vertexai or getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"

        if not vertexai:
            self.api_key = self.api_key or getenv("GOOGLE_API_KEY")
            if not self.api_key:
                log_error("GOOGLE_API_KEY not set. Please set the GOOGLE_API_KEY environment variable.")
            _client_params["api_key"] = self.api_key
        else:
            log_info("Using Vertex AI API for embeddings")
            _client_params["vertexai"] = True
            _client_params["project"] = self.project_id or getenv("GOOGLE_CLOUD_PROJECT")
            _client_params["location"] = self.location or getenv("GOOGLE_CLOUD_LOCATION")

        _client_params = {k: v for k, v in _client_params.items() if v is not None}

        if self.client_params:
            _client_params.update(self.client_params)

        _client_params = inject_agno_client_header(_client_params)

        self.gemini_client = genai.Client(**_client_params)

        return self.gemini_client

    @property
    def aclient(self) -> GeminiClient:
        """Returns the same client instance since Google GenAI Client supports both sync and async operations."""
        return self.client

    def _response(self, text: str) -> EmbedContentResponse:
        # If a user provides a model id with the `models/` prefix, we need to remove it
        _id = self.id
        if _id.startswith("models/"):
            _id = _id.split("/")[-1]

        _request_params: Dict[str, Any] = {"contents": text, "model": _id, "config": {}}
        if self.dimensions:
            _request_params["config"]["output_dimensionality"] = self.dimensions
        if self.task_type:
            _request_params["config"]["task_type"] = self.task_type
        if self.title:
            _request_params["config"]["title"] = self.title
        if not _request_params["config"]:
            del _request_params["config"]

        if self.request_params:
            _request_params.update(self.request_params)
        return self.client.models.embed_content(**_request_params)

    def get_embedding(self, text: str) -> List[float]:
        try:
            response = self._response(text=text)
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="Google")

        # A 200 carrying no embedding is a valid provider response, not a failure, so it
        # is reported as an empty vector. Ingestion counts unembedded chunks and reports
        # the shortfall as PARTIAL; raising here would fail callers that tolerate it.
        if response.embeddings and len(response.embeddings) > 0:
            values = response.embeddings[0].values
            if values is not None:
                return values
        log_warning("No embeddings found in response")
        return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        try:
            response = self._response(text=text)
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="Google")
        usage = None
        if response.metadata and hasattr(response.metadata, "billable_character_count"):
            usage = {"billable_character_count": response.metadata.billable_character_count}

        try:
            if response.embeddings and len(response.embeddings) > 0:
                values = response.embeddings[0].values
                if values is not None:
                    return values, usage
            log_info("No embeddings found in response")
            return [], usage
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="Google")

    async def async_get_embedding(self, text: str) -> List[float]:
        """Async version of get_embedding using client.aio."""
        # If a user provides a model id with the `models/` prefix, we need to remove it
        _id = self.id
        if _id.startswith("models/"):
            _id = _id.split("/")[-1]

        _request_params: Dict[str, Any] = {"contents": text, "model": _id, "config": {}}
        if self.dimensions:
            _request_params["config"]["output_dimensionality"] = self.dimensions
        if self.task_type:
            _request_params["config"]["task_type"] = self.task_type
        if self.title:
            _request_params["config"]["title"] = self.title
        if not _request_params["config"]:
            del _request_params["config"]

        if self.request_params:
            _request_params.update(self.request_params)

        try:
            response = await self.aclient.aio.models.embed_content(**_request_params)
            if response.embeddings and len(response.embeddings) > 0:
                values = response.embeddings[0].values
                if values is not None:
                    return values
            log_info("No embeddings found in response")
            return []
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="Google")

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        """Async version of get_embedding_and_usage using client.aio."""
        # If a user provides a model id with the `models/` prefix, we need to remove it
        _id = self.id
        if _id.startswith("models/"):
            _id = _id.split("/")[-1]

        _request_params: Dict[str, Any] = {"contents": text, "model": _id, "config": {}}
        if self.dimensions:
            _request_params["config"]["output_dimensionality"] = self.dimensions
        if self.task_type:
            _request_params["config"]["task_type"] = self.task_type
        if self.title:
            _request_params["config"]["title"] = self.title
        if not _request_params["config"]:
            del _request_params["config"]

        if self.request_params:
            _request_params.update(self.request_params)

        try:
            response = await self.aclient.aio.models.embed_content(**_request_params)
            usage = None
            if response.metadata and hasattr(response.metadata, "billable_character_count"):
                usage = {"billable_character_count": response.metadata.billable_character_count}

            if response.embeddings and len(response.embeddings) > 0:
                values = response.embeddings[0].values
                if values is not None:
                    return values, usage
            log_info("No embeddings found in response")
            return [], usage
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="Google")

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict[str, Any]]]]:
        """
        Get embeddings and usage for multiple texts in batches.

        Args:
            texts: List of text strings to embed

        Returns:
            Tuple of (List of embedding vectors, List of usage dictionaries)
        """
        all_embeddings: List[List[float]] = []
        all_usage: List[Optional[Dict[str, Any]]] = []
        log_info(f"Getting embeddings and usage for {len(texts)} texts in batches of {self.batch_size}")

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]

            # If a user provides a model id with the `models/` prefix, we need to remove it
            _id = self.id
            if _id.startswith("models/"):
                _id = _id.split("/")[-1]

            _request_params: Dict[str, Any] = {"contents": batch_texts, "model": _id, "config": {}}
            if self.dimensions:
                _request_params["config"]["output_dimensionality"] = self.dimensions
            if self.task_type:
                _request_params["config"]["task_type"] = self.task_type
            if self.title:
                _request_params["config"]["title"] = self.title
            if not _request_params["config"]:
                del _request_params["config"]

            if self.request_params:
                _request_params.update(self.request_params)

            try:
                response = await self.aclient.aio.models.embed_content(**_request_params)

                # A batch that comes back short or empty is reported per text, not raised:
                # an empty embedding is a valid response, and the caller counts unembedded
                # chunks. Missing entries become empty vectors so positions stay aligned.
                batch_embeddings = pad_batch_embeddings(
                    [e.values if e.values is not None else [] for e in (response.embeddings or [])],
                    batch_texts,
                    "Google",
                )
                if len(batch_embeddings) < len(batch_texts):
                    log_warning(f"Batch response returned {len(batch_embeddings)} of {len(batch_texts)} embeddings")
                    batch_embeddings.extend([[]] * (len(batch_texts) - len(batch_embeddings)))
                all_embeddings.extend(batch_embeddings)

                # Extract usage information
                usage_dict = None
                if response.metadata and hasattr(response.metadata, "billable_character_count"):
                    usage_dict = {"billable_character_count": response.metadata.billable_character_count}

                # Add same usage info for each embedding in the batch
                all_usage.extend([usage_dict] * len(batch_texts))

            except Exception as e:
                log_warning(f"Error in async batch embedding: {str(e)}")
                # Fall back to individual calls: a whole-batch failure is often transient
                # (or caused by a single bad text). Successes are kept so one bad chunk
                # does not discard the rest of the batch.
                batch_embeddings, batch_usage = await aembed_texts_individually(self, batch_texts)
                all_embeddings.extend(batch_embeddings)
                all_usage.extend(batch_usage)

        return all_embeddings, all_usage
