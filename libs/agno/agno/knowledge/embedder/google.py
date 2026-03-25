from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agno.knowledge.embedder.base import ContentInput, Embedder, EmbeddingInput
from agno.media import Audio, Image, Video
from agno.utils.log import log_error, log_info, log_warning

try:
    from google import genai
    from google.genai import Client as GeminiClient
    from google.genai import types
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

        self.gemini_client = genai.Client(**_client_params)

        return self.gemini_client

    @property
    def aclient(self) -> GeminiClient:
        """Returns the same client instance since Google GenAI Client supports both sync and async operations."""
        return self.client

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_model_id(self) -> str:
        _id = self.id
        if _id.startswith("models/"):
            _id = _id.split("/")[-1]
        return _id

    def _supports_multimodal(self) -> bool:
        """Check if the current model supports multimodal embeddings."""
        _id = self._get_model_id().lower()
        return "embedding-2" in _id

    def _require_multimodal(self) -> None:
        """Raise if the current model does not support multimodal embeddings."""
        if not self._supports_multimodal():
            raise ValueError(
                f"Model '{self.id}' does not support multimodal embeddings. "
                "Use a multimodal model such as 'gemini-embedding-2-preview'."
            )

    def _build_config(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {}
        if self.dimensions:
            config["output_dimensionality"] = self.dimensions
        if self.task_type:
            config["task_type"] = self.task_type
        if self.title:
            config["title"] = self.title
        return config

    def _build_request_params(self, contents: Any) -> Dict[str, Any]:
        _request_params: Dict[str, Any] = {
            "contents": contents,
            "model": self._get_model_id(),
        }
        config = self._build_config()
        if config:
            _request_params["config"] = config
        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params

    @staticmethod
    def _infer_mime_type(media: Any, default: str) -> str:
        """Infer MIME type from a media object's mime_type, format, or filepath extension.

        Falls back to the provided default if inference fails.
        """
        if media.mime_type:
            return media.mime_type

        ext = None
        if hasattr(media, "format") and media.format:
            ext = media.format.lower()

        if ext is None and hasattr(media, "filepath") and media.filepath:
            import os

            ext = os.path.splitext(str(media.filepath))[1].lstrip(".").lower()

        if ext:
            import mimetypes

            guessed = mimetypes.guess_type(f"file.{ext}")[0]
            if guessed:
                return guessed

        return default

    @staticmethod
    def _build_contents(content: Sequence[EmbeddingInput]) -> list:
        """Convert agno media types to Gemini Part objects."""
        if isinstance(content, str):
            raise TypeError(
                "Expected a list of inputs, not a plain string. "
                "Use get_embedding('text') for text-only embedding, or wrap in a list: ['text']"
            )
        parts: list = []
        for item in content:
            if isinstance(item, str):
                parts.append(types.Part.from_text(text=item))
            elif isinstance(item, Image):
                data = item.get_content_bytes()
                if data is None:
                    raise ValueError("Image has no content bytes")
                mime = GeminiEmbedder._infer_mime_type(item, "image/png")
                parts.append(types.Part.from_bytes(data=data, mime_type=mime))
            elif isinstance(item, Audio):
                data = item.get_content_bytes()
                if data is None:
                    raise ValueError("Audio has no content bytes")
                mime = GeminiEmbedder._infer_mime_type(item, "audio/wav")
                parts.append(types.Part.from_bytes(data=data, mime_type=mime))
            elif isinstance(item, Video):
                data = item.get_content_bytes()
                if data is None:
                    raise ValueError("Video has no content bytes")
                mime = GeminiEmbedder._infer_mime_type(item, "video/mp4")
                parts.append(types.Part.from_bytes(data=data, mime_type=mime))
            else:
                raise TypeError(f"Unsupported content type: {type(item)}")
        return parts

    def _embed_parts(self, parts: list) -> EmbedContentResponse:
        """Sync embed a list of Gemini Part objects."""
        return self.client.models.embed_content(**self._build_request_params(parts))

    async def _async_embed_parts(self, parts: list) -> EmbedContentResponse:
        """Async embed a list of Gemini Part objects."""
        return await self.aclient.aio.models.embed_content(**self._build_request_params(parts))

    @staticmethod
    def _extract_embedding(response: EmbedContentResponse) -> List[float]:
        if response.embeddings and len(response.embeddings) > 0:
            values = response.embeddings[0].values
            if values is not None:
                return values
        log_info("No embeddings found in response")
        return []

    @staticmethod
    def _extract_usage(response: EmbedContentResponse) -> Optional[Dict]:
        if response.metadata and hasattr(response.metadata, "billable_character_count"):
            return {"billable_character_count": response.metadata.billable_character_count}
        return None

    def _is_media(self, content: ContentInput) -> bool:
        """Return True if content is a media object or a sequence of inputs."""
        return isinstance(content, (Image, Audio, Video, list, tuple))

    # ------------------------------------------------------------------
    # Unified embedding methods
    # ------------------------------------------------------------------

    def _response(self, text: str) -> EmbedContentResponse:
        return self.client.models.embed_content(**self._build_request_params(text))

    def get_embedding(self, content: ContentInput) -> List[float]:
        if isinstance(content, str):
            response = self._response(text=content)
            try:
                return self._extract_embedding(response)
            except Exception as e:
                log_error(f"Error extracting embeddings: {e}")
                return []

        self._require_multimodal()
        if isinstance(content, (Image, Audio, Video)):
            parts = self._build_contents([content])
        else:
            parts = self._build_contents(content)
        response = self._embed_parts(parts)
        return self._extract_embedding(response)

    def get_embedding_and_usage(self, content: ContentInput) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        if isinstance(content, str):
            response = self._response(text=content)
            usage = self._extract_usage(response)
            try:
                return self._extract_embedding(response), usage
            except Exception as e:
                log_error(f"Error extracting embeddings: {e}")
                return [], usage

        self._require_multimodal()
        if isinstance(content, (Image, Audio, Video)):
            parts = self._build_contents([content])
        else:
            parts = self._build_contents(content)
        response = self._embed_parts(parts)
        return self._extract_embedding(response), self._extract_usage(response)

    async def async_get_embedding(self, content: ContentInput) -> List[float]:
        if isinstance(content, str):
            try:
                response = await self.aclient.aio.models.embed_content(**self._build_request_params(content))
                return self._extract_embedding(response)
            except Exception as e:
                log_error(f"Error extracting embeddings: {e}")
                return []

        self._require_multimodal()
        if isinstance(content, (Image, Audio, Video)):
            parts = self._build_contents([content])
        else:
            parts = self._build_contents(content)
        response = await self._async_embed_parts(parts)
        return self._extract_embedding(response)

    async def async_get_embedding_and_usage(
        self, content: ContentInput
    ) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        if isinstance(content, str):
            try:
                response = await self.aclient.aio.models.embed_content(**self._build_request_params(content))
                usage = self._extract_usage(response)
                return self._extract_embedding(response), usage
            except Exception as e:
                log_error(f"Error extracting embeddings: {e}")
                return [], None

        self._require_multimodal()
        if isinstance(content, (Image, Audio, Video)):
            parts = self._build_contents([content])
        else:
            parts = self._build_contents(content)
        response = await self._async_embed_parts(parts)
        return self._extract_embedding(response), self._extract_usage(response)

    # ------------------------------------------------------------------
    # Batch embedding (text-only)
    # ------------------------------------------------------------------

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

            try:
                response = await self.aclient.aio.models.embed_content(**self._build_request_params(batch_texts))

                # Extract embeddings from batch response
                if response.embeddings:
                    batch_embeddings = []
                    for embedding in response.embeddings:
                        if embedding.values is not None:
                            batch_embeddings.append(embedding.values)
                        else:
                            batch_embeddings.append([])
                    all_embeddings.extend(batch_embeddings)
                else:
                    # If no embeddings, add empty lists for each text in batch
                    all_embeddings.extend([[] for _ in batch_texts])

                # Extract usage information
                usage_dict = self._extract_usage(response)

                # Add same usage info for each embedding in the batch
                all_usage.extend([usage_dict] * len(batch_texts))

            except Exception as e:
                log_warning(f"Error in async batch embedding: {e}")
                # Fallback to individual calls for this batch
                for text in batch_texts:
                    try:
                        text_embedding: List[float]
                        text_usage: Optional[Dict[str, Any]]
                        text_embedding, text_usage = await self.async_get_embedding_and_usage(text)
                        all_embeddings.append(text_embedding)
                        all_usage.append(text_usage)
                    except Exception as e2:
                        log_warning(f"Error in individual async embedding fallback: {e2}")
                        all_embeddings.append([])
                        all_usage.append(None)

        return all_embeddings, all_usage
