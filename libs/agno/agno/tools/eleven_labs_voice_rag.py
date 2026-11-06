"""
ElevenLabs Voice RAG Tools

A comprehensive toolkit for building Voice RAG (Retrieval-Augmented Generation) agents
using ElevenLabs Conversational AI. Enables real-time speech-to-speech conversations
with knowledge base integration.

Features:
- Upload documents (PDF, TXT, DOCX) to ElevenLabs Knowledge Base
- Create content from URLs or raw text
- Automatic RAG index computation for better retrieval
- Create voice agents with RAG capabilities
- Get signed WebSocket URLs for real-time voice conversations
- Support for multiple languages including Hindi
- Configurable LLM (GPT-4, Gemini, Claude, Qwen3)
- Configurable voice settings

Usage:
    from agno.agent import Agent
    from agno.tools.eleven_labs_voice_rag import ElevenLabsVoiceRAGTools

    agent = Agent(
        tools=[ElevenLabsVoiceRAGTools(
            voice_id="cjVigY5qzO86Huf0OWal",
            language="en",
            llm="qwen3-30b-a3b"
        )],
        instructions=["Use ElevenLabs to create voice agents with RAG capabilities"]
    )
"""

import json
import webbrowser
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, log_warning

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


# Supported LLM models
ElevenLabsLLM = Literal[
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4",
    "gpt-3.5-turbo",
    "claude-3-5-sonnet",
    "claude-3-haiku",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-2.0-flash-exp",
    "qwen3-30b-a3b",  # Ultra low latency ~200ms
    "deepseek-r1",
]

# Supported languages
ElevenLabsLanguage = Literal[
    "en",  # English
    "es",  # Spanish
    "fr",  # French
    "de",  # German
    "it",  # Italian
    "pt",  # Portuguese
    "hi",  # Hindi
    "ja",  # Japanese
    "ko",  # Korean
    "zh",  # Chinese
    "ar",  # Arabic
    "ru",  # Russian
]

# RAG embedding models
RAGEmbeddingModel = Literal[
    "e5_mistral_7b_instruct",
    "multilingual_e5_large_instruct",  # Recommended for multi-language
]


class ElevenLabsVoiceRAGTools(Toolkit):
    """
    ElevenLabs Voice RAG Toolkit

    A comprehensive toolkit for building voice-enabled RAG agents using
    ElevenLabs Conversational AI platform.

    Args:
        api_key: ElevenLabs API key (or set ELEVEN_LABS_API_KEY env var)
        voice_id: Default voice ID for agents
        language: Default language for agents
        llm: Default LLM model for agents
        rag_embedding_model: Model for RAG embeddings
        enable_upload_document: Enable document upload tool
        enable_create_from_url: Enable URL content creation tool
        enable_create_from_text: Enable text content creation tool
        enable_create_agent: Enable agent creation tool
        enable_get_conversation_url: Enable conversation URL tool
        enable_list_voices: Enable voice listing tool
        enable_list_documents: Enable document listing tool
        auto_compute_rag_index: Automatically compute RAG index after upload
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: str = "cjVigY5qzO86Huf0OWal",  # Eric - reliable default
        language: ElevenLabsLanguage = "en",
        llm: ElevenLabsLLM = "qwen3-30b-a3b",
        rag_embedding_model: RAGEmbeddingModel = "multilingual_e5_large_instruct",
        enable_upload_document: bool = True,
        enable_create_from_url: bool = True,
        enable_create_from_text: bool = True,
        enable_create_agent: bool = True,
        enable_get_conversation_url: bool = True,
        enable_list_voices: bool = True,
        enable_list_documents: bool = True,
        auto_compute_rag_index: bool = True,
        **kwargs,
    ):
        # API Configuration
        self.api_key = api_key or getenv("ELEVEN_LABS_API_KEY") or getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            log_warning("ELEVEN_LABS_API_KEY not set. Please set the environment variable.")

        self.base_url = "https://api.elevenlabs.io/v1"

        # Default settings
        self.default_voice_id = voice_id
        self.default_language = language
        self.default_llm = llm
        self.rag_embedding_model = rag_embedding_model
        self.auto_compute_rag_index = auto_compute_rag_index

        # Track created resources for cleanup
        self._uploaded_documents: List[str] = []
        self._created_agents: List[str] = []

        # Build tools list
        tools: List[Any] = []

        if enable_upload_document:
            tools.append(self.upload_document)
        if enable_create_from_url:
            tools.append(self.create_from_url)
        if enable_create_from_text:
            tools.append(self.create_from_text)
        if enable_create_agent:
            tools.append(self.create_voice_agent)
        if enable_get_conversation_url:
            tools.append(self.get_conversation_url)
        if enable_list_voices:
            tools.append(self.list_voices)
        if enable_list_documents:
            tools.append(self.list_documents)

        # Async tools
        async_tools = [
            (self.aupload_document, "upload_document"),
            (self.acreate_from_url, "create_from_url"),
            (self.acreate_from_text, "create_from_text"),
            (self.acreate_voice_agent, "create_voice_agent"),
            (self.aget_conversation_url, "get_conversation_url"),
            (self.alist_voices, "list_voices"),
            (self.alist_documents, "list_documents"),
        ]

        super().__init__(name="elevenlabs_voice_rag_tools", tools=tools, async_tools=async_tools, **kwargs)

    def _get_headers(self, include_content_type: bool = True) -> Dict[str, str]:
        """Get request headers"""
        headers = {"xi-api-key": self.api_key}
        if include_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _get_content_type(self, filename: str) -> str:
        """Get content type based on file extension"""
        content_type_map = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".csv": "text/csv",
            ".json": "application/json",
            ".md": "text/markdown",
        }
        ext = Path(filename).suffix.lower()
        return content_type_map.get(ext, "application/octet-stream")

    # ==================== Sync Methods ====================

    def upload_document(
        self,
        file_path: str,
        name: Optional[str] = None,
    ) -> str:
        """
        Upload a document to ElevenLabs Knowledge Base for RAG.

        Supports PDF, TXT, DOCX, CSV, JSON, and Markdown files.
        The document will be indexed for retrieval by voice agents.

        Args:
            file_path: Path to the file to upload
            name: Optional custom name for the document

        Returns:
            str: JSON with document_id and upload status
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return json.dumps({"error": f"File not found: {file_path}"})

            filename = path.name
            content_type = self._get_content_type(filename)

            with open(path, "rb") as f:
                file_content = f.read()

            files = {"file": (filename, file_content, content_type)}
            data = {}
            if name:
                data["name"] = name

            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    f"{self.base_url}/convai/knowledge-base/file",
                    headers=self._get_headers(include_content_type=False),
                    files=files,
                    data=data,
                )
                response.raise_for_status()
                result = response.json()

            document_id = result.get("id")
            if document_id:
                self._uploaded_documents.append(document_id)
                log_info(f"Uploaded document: {filename} -> {document_id}")

                # Auto-compute RAG index
                if self.auto_compute_rag_index:
                    self._compute_rag_index_sync(document_id)

            return json.dumps(
                {
                    "success": True,
                    "document_id": document_id,
                    "name": result.get("name", filename),
                    "message": f"Document '{filename}' uploaded successfully",
                }
            )

        except Exception as e:
            log_error(f"Failed to upload document: {e}")
            return json.dumps({"error": str(e)})

    def create_from_url(
        self,
        url: str,
        name: Optional[str] = None,
    ) -> str:
        """
        Create a knowledge base document from a URL.

        Fetches content from the URL and adds it to the knowledge base.
        Useful for adding web pages, documentation, or online content.

        Args:
            url: The URL to fetch content from
            name: Optional custom name for the document

        Returns:
            str: JSON with document_id and creation status
        """
        try:
            data = {"url": url}
            if name:
                data["name"] = name

            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    f"{self.base_url}/convai/knowledge-base/url", headers=self._get_headers(), json=data
                )
                response.raise_for_status()
                result = response.json()

            document_id = result.get("id")
            if document_id:
                self._uploaded_documents.append(document_id)
                log_info(f"Created document from URL: {url} -> {document_id}")

                if self.auto_compute_rag_index:
                    self._compute_rag_index_sync(document_id)

            return json.dumps(
                {
                    "success": True,
                    "document_id": document_id,
                    "source_url": url,
                    "message": "Document created from URL successfully",
                }
            )

        except Exception as e:
            log_error(f"Failed to create from URL: {e}")
            return json.dumps({"error": str(e)})

    def create_from_text(
        self,
        text: str,
        name: str,
    ) -> str:
        """
        Create a knowledge base document from raw text.

        Useful for adding custom content, FAQs, or any text-based information.

        Args:
            text: The text content to add
            name: Name for the document

        Returns:
            str: JSON with document_id and creation status
        """
        try:
            data = {"text": text, "name": name}

            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.base_url}/convai/knowledge-base/text", headers=self._get_headers(), json=data
                )
                response.raise_for_status()
                result = response.json()

            document_id = result.get("id")
            if document_id:
                self._uploaded_documents.append(document_id)
                log_info(f"Created document from text: {name} -> {document_id}")

                if self.auto_compute_rag_index:
                    self._compute_rag_index_sync(document_id)

            return json.dumps(
                {
                    "success": True,
                    "document_id": document_id,
                    "name": name,
                    "message": f"Document '{name}' created successfully",
                }
            )

        except Exception as e:
            log_error(f"Failed to create from text: {e}")
            return json.dumps({"error": str(e)})

    def _compute_rag_index_sync(self, document_id: str) -> None:
        """Compute RAG index for a document (sync)"""
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.base_url}/convai/knowledge-base/{document_id}/rag-index",
                    headers=self._get_headers(),
                    json={"model": self.rag_embedding_model},
                )
                if response.status_code == 200:
                    log_info(f"RAG index computation started for {document_id}")
                else:
                    log_warning(f"RAG index computation failed: {response.text}")
        except Exception as e:
            log_warning(f"Failed to compute RAG index: {e}")

    def create_voice_agent(
        self,
        name: str,
        system_prompt: str,
        first_message: str = "Hello! How can I help you today?",
        knowledge_base_ids: Optional[List[str]] = None,
        voice_id: Optional[str] = None,
        language: Optional[str] = None,
        llm: Optional[str] = None,
    ) -> str:
        """
        Create an ElevenLabs voice agent with RAG capabilities.

        The agent can have real-time voice conversations and retrieve
        information from attached knowledge base documents.

        Args:
            name: Name for the agent
            system_prompt: Instructions for how the agent should behave
            first_message: The greeting message when conversation starts
            knowledge_base_ids: List of document IDs to attach (from uploads)
            voice_id: Voice ID for TTS (uses default if not specified)
            language: Language code (e.g., "en", "hi", "es")
            llm: LLM model to use (e.g., "qwen3-30b-a3b", "gpt-4o")

        Returns:
            str: JSON with agent_id and conversation URL
        """
        try:
            voice = voice_id or self.default_voice_id
            lang = language or self.default_language
            model = llm or self.default_llm

            # Use uploaded documents if none specified
            kb_ids = knowledge_base_ids or self._uploaded_documents

            # Format knowledge base objects
            knowledge_base_objects = [{"type": "file", "id": kb_id, "name": ""} for kb_id in kb_ids] if kb_ids else []

            # Build conversation config
            conversation_config = {
                "agent": {
                    "prompt": {
                        "prompt": system_prompt,
                        "llm": model,
                        "knowledge_base": knowledge_base_objects,
                        "rag": {
                            "enabled": True,
                            "embedding_model": self.rag_embedding_model,
                            "max_vector_distance": 0.6,
                            "max_documents_length": 50000,
                        },
                    },
                    "first_message": first_message,
                    "language": lang,
                },
                "tts": {
                    "voice_id": voice,
                    "model_id": "eleven_turbo_v2",
                    "stability": 0.5,
                    "similarity_boost": 0.8,
                    "speed": 1.0,
                },
                "asr": {"provider": "elevenlabs", "quality": "high"},
                "turn": {"turn_timeout": 7, "turn_eagerness": "normal"},
                "conversation": {"max_duration_seconds": 600},
            }

            data = {
                "name": name,
                "conversation_config": conversation_config,
                "platform_settings": {
                    "auth": {
                        "enable_auth": False,
                        "allowlist": [
                            {"hostname": "localhost"},
                            {"hostname": "localhost:8080"},
                            {"hostname": "localhost:3000"},
                            {"hostname": "127.0.0.1"},
                            {"hostname": "127.0.0.1:8080"},
                        ],
                    }
                },
                "tags": ["agno", "voice-rag"],
            }

            with httpx.Client(timeout=60.0) as client:
                response = client.post(f"{self.base_url}/convai/agents/create", headers=self._get_headers(), json=data)
                response.raise_for_status()
                result = response.json()

            agent_id = result.get("agent_id")
            if agent_id:
                self._created_agents.append(agent_id)
                log_info(f"Created voice agent: {name} -> {agent_id}")

            # Get conversation URL
            conversation_url = None
            try:
                with httpx.Client(timeout=30.0) as client:
                    url_response = client.get(
                        f"{self.base_url}/convai/conversation/get-signed-url",
                        headers=self._get_headers(),
                        params={"agent_id": agent_id},
                    )
                    if url_response.status_code == 200:
                        conversation_url = url_response.json().get("signed_url")
            except Exception:
                pass

            return json.dumps(
                {
                    "success": True,
                    "agent_id": agent_id,
                    "name": name,
                    "voice_id": voice,
                    "language": lang,
                    "llm": model,
                    "knowledge_base_count": len(kb_ids),
                    "conversation_url": conversation_url,
                    "embed_code": f'<elevenlabs-convai agent-id="{agent_id}"></elevenlabs-convai><script src="https://unpkg.com/@elevenlabs/convai-widget-embed" async type="text/javascript"></script>',
                    "dashboard_url": "https://elevenlabs.io/app/conversational-ai",
                    "widget_url": f"http://localhost:8080/voice_chat.html?agent_id={agent_id}",
                    "message": f"Voice agent '{name}' created with public access enabled! Add embed_code to your HTML or open widget_url to start voice chat.",
                }
            )

        except Exception as e:
            log_error(f"Failed to create voice agent: {e}")
            return json.dumps({"error": str(e)})

    def get_conversation_url(
        self,
        agent_id: str,
        open_in_browser: bool = False,
    ) -> str:
        """
        Get a signed WebSocket URL to start a voice conversation.

        This URL can be used to connect to the agent for real-time
        speech-to-speech conversation.

        Args:
            agent_id: The agent ID to connect to
            open_in_browser: Whether to open the dashboard in browser

        Returns:
            str: JSON with signed WebSocket URL and embed instructions
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(
                    f"{self.base_url}/convai/conversation/get-signed-url",
                    headers=self._get_headers(),
                    params={"agent_id": agent_id},
                )
                response.raise_for_status()
                result = response.json()

            signed_url = result.get("signed_url")
            dashboard_url = "https://elevenlabs.io/app/conversational-ai"
            embed_code = f'<elevenlabs-convai agent-id="{agent_id}"></elevenlabs-convai><script src="https://unpkg.com/@elevenlabs/convai-widget-embed" async type="text/javascript"></script>'

            if open_in_browser:
                webbrowser.open(dashboard_url)
                log_info("Opened agent dashboard in browser")

            return json.dumps(
                {
                    "success": True,
                    "agent_id": agent_id,
                    "signed_url": signed_url,
                    "embed_code": embed_code,
                    "dashboard_url": dashboard_url,
                    "message": f"Agent ID: {agent_id}. Add embed_code to your HTML to start voice chat. Enable 'Public Access' in dashboard first.",
                }
            )

        except Exception as e:
            log_error(f"Failed to get conversation URL: {e}")
            return json.dumps({"error": str(e)})

    def list_voices(self) -> str:
        """
        List available voices for voice agents.

        Returns:
            str: JSON list of available voices with IDs and names
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(f"{self.base_url}/voices", headers=self._get_headers())
                response.raise_for_status()
                result = response.json()

            voices = []
            for voice in result.get("voices", [])[:20]:  # Limit to 20
                voices.append(
                    {
                        "voice_id": voice.get("voice_id"),
                        "name": voice.get("name"),
                        "category": voice.get("category"),
                        "labels": voice.get("labels", {}),
                    }
                )

            return json.dumps({"success": True, "voices": voices, "total": len(voices)})

        except Exception as e:
            log_error(f"Failed to list voices: {e}")
            return json.dumps({"error": str(e)})

    def list_documents(self) -> str:
        """
        List documents in the knowledge base.

        Returns:
            str: JSON list of documents with IDs and names
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(
                    f"{self.base_url}/convai/knowledge-base", headers=self._get_headers(), params={"page_size": 30}
                )
                response.raise_for_status()
                result = response.json()

            documents = []
            for doc in result.get("documents", []):
                documents.append(
                    {
                        "document_id": doc.get("id"),
                        "name": doc.get("name"),
                        "type": doc.get("type"),
                        "status": doc.get("status"),
                        "created_at": doc.get("created_at_unix_secs"),
                    }
                )

            return json.dumps(
                {
                    "success": True,
                    "documents": documents,
                    "total": len(documents),
                    "uploaded_in_session": self._uploaded_documents,
                }
            )

        except Exception as e:
            log_error(f"Failed to list documents: {e}")
            return json.dumps({"error": str(e)})

    # ==================== Async Methods ====================

    async def aupload_document(
        self,
        file_path: str,
        name: Optional[str] = None,
    ) -> str:
        """
        Upload a document to ElevenLabs Knowledge Base (async).

        Args:
            file_path: Path to the file to upload
            name: Optional custom name for the document

        Returns:
            str: JSON with document_id and upload status
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return json.dumps({"error": f"File not found: {file_path}"})

            filename = path.name
            content_type = self._get_content_type(filename)

            with open(path, "rb") as f:
                file_content = f.read()

            files = {"file": (filename, file_content, content_type)}
            data = {}
            if name:
                data["name"] = name

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/convai/knowledge-base/file",
                    headers=self._get_headers(include_content_type=False),
                    files=files,
                    data=data,
                )
                response.raise_for_status()
                result = response.json()

            document_id = result.get("id")
            if document_id:
                self._uploaded_documents.append(document_id)
                log_info(f"Uploaded document: {filename} -> {document_id}")

                if self.auto_compute_rag_index:
                    await self._acompute_rag_index(document_id)

            return json.dumps(
                {
                    "success": True,
                    "document_id": document_id,
                    "name": result.get("name", filename),
                    "message": f"Document '{filename}' uploaded successfully",
                }
            )

        except Exception as e:
            log_error(f"Failed to upload document: {e}")
            return json.dumps({"error": str(e)})

    async def acreate_from_url(
        self,
        url: str,
        name: Optional[str] = None,
    ) -> str:
        """Create a knowledge base document from a URL (async)."""
        try:
            data = {"url": url}
            if name:
                data["name"] = name

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/convai/knowledge-base/url", headers=self._get_headers(), json=data
                )
                response.raise_for_status()
                result = response.json()

            document_id = result.get("id")
            if document_id:
                self._uploaded_documents.append(document_id)
                log_info(f"Created document from URL: {url} -> {document_id}")

                if self.auto_compute_rag_index:
                    await self._acompute_rag_index(document_id)

            return json.dumps(
                {
                    "success": True,
                    "document_id": document_id,
                    "source_url": url,
                    "message": "Document created from URL successfully",
                }
            )

        except Exception as e:
            log_error(f"Failed to create from URL: {e}")
            return json.dumps({"error": str(e)})

    async def acreate_from_text(
        self,
        text: str,
        name: str,
    ) -> str:
        """Create a knowledge base document from raw text (async)."""
        try:
            data = {"text": text, "name": name}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/convai/knowledge-base/text", headers=self._get_headers(), json=data
                )
                response.raise_for_status()
                result = response.json()

            document_id = result.get("id")
            if document_id:
                self._uploaded_documents.append(document_id)
                log_info(f"Created document from text: {name} -> {document_id}")

                if self.auto_compute_rag_index:
                    await self._acompute_rag_index(document_id)

            return json.dumps(
                {
                    "success": True,
                    "document_id": document_id,
                    "name": name,
                    "message": f"Document '{name}' created successfully",
                }
            )

        except Exception as e:
            log_error(f"Failed to create from text: {e}")
            return json.dumps({"error": str(e)})

    async def _acompute_rag_index(self, document_id: str) -> None:
        """Compute RAG index for a document (async)"""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/convai/knowledge-base/{document_id}/rag-index",
                    headers=self._get_headers(),
                    json={"model": self.rag_embedding_model},
                )
                if response.status_code == 200:
                    log_info(f"RAG index computation started for {document_id}")
                else:
                    log_warning(f"RAG index computation failed: {response.text}")
        except Exception as e:
            log_warning(f"Failed to compute RAG index: {e}")

    async def acreate_voice_agent(
        self,
        name: str,
        system_prompt: str,
        first_message: str = "Hello! How can I help you today?",
        knowledge_base_ids: Optional[List[str]] = None,
        voice_id: Optional[str] = None,
        language: Optional[str] = None,
        llm: Optional[str] = None,
    ) -> str:
        """Create an ElevenLabs voice agent with RAG capabilities (async)."""
        try:
            voice = voice_id or self.default_voice_id
            lang = language or self.default_language
            model = llm or self.default_llm

            kb_ids = knowledge_base_ids or self._uploaded_documents

            knowledge_base_objects = [{"type": "file", "id": kb_id, "name": ""} for kb_id in kb_ids] if kb_ids else []

            conversation_config = {
                "agent": {
                    "prompt": {
                        "prompt": system_prompt,
                        "llm": model,
                        "knowledge_base": knowledge_base_objects,
                        "rag": {
                            "enabled": True,
                            "embedding_model": self.rag_embedding_model,
                            "max_vector_distance": 0.6,
                            "max_documents_length": 50000,
                        },
                    },
                    "first_message": first_message,
                    "language": lang,
                },
                "tts": {
                    "voice_id": voice,
                    "model_id": "eleven_turbo_v2",
                    "stability": 0.5,
                    "similarity_boost": 0.8,
                    "speed": 1.0,
                },
                "asr": {"provider": "elevenlabs", "quality": "high"},
                "turn": {"turn_timeout": 7, "turn_eagerness": "normal"},
                "conversation": {"max_duration_seconds": 600},
            }

            data = {
                "name": name,
                "conversation_config": conversation_config,
                "platform_settings": {
                    "auth": {
                        "enable_auth": False,
                        "allowlist": [
                            {"hostname": "localhost"},
                            {"hostname": "localhost:8080"},
                            {"hostname": "localhost:3000"},
                            {"hostname": "127.0.0.1"},
                            {"hostname": "127.0.0.1:8080"},
                        ],
                    }
                },
                "tags": ["agno", "voice-rag"],
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/convai/agents/create", headers=self._get_headers(), json=data
                )
                response.raise_for_status()
                result = response.json()

            agent_id = result.get("agent_id")
            if agent_id:
                self._created_agents.append(agent_id)
                log_info(f"Created voice agent: {name} -> {agent_id}")

            # Get conversation URL
            conversation_url = None
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    url_response = await client.get(
                        f"{self.base_url}/convai/conversation/get-signed-url",
                        headers=self._get_headers(),
                        params={"agent_id": agent_id},
                    )
                    if url_response.status_code == 200:
                        conversation_url = url_response.json().get("signed_url")
            except Exception:
                pass

            return json.dumps(
                {
                    "success": True,
                    "agent_id": agent_id,
                    "name": name,
                    "voice_id": voice,
                    "language": lang,
                    "llm": model,
                    "knowledge_base_count": len(kb_ids),
                    "conversation_url": conversation_url,
                    "embed_code": f'<elevenlabs-convai agent-id="{agent_id}"></elevenlabs-convai><script src="https://unpkg.com/@elevenlabs/convai-widget-embed" async type="text/javascript"></script>',
                    "dashboard_url": "https://elevenlabs.io/app/conversational-ai",
                    "widget_url": f"http://localhost:8080/voice_chat.html?agent_id={agent_id}",
                    "message": f"Voice agent '{name}' created with public access enabled! Add embed_code to your HTML or open widget_url to start voice chat.",
                }
            )

        except Exception as e:
            log_error(f"Failed to create voice agent: {e}")
            return json.dumps({"error": str(e)})

    async def aget_conversation_url(
        self,
        agent_id: str,
        open_in_browser: bool = False,
    ) -> str:
        """Get a signed WebSocket URL for voice conversation (async)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/convai/conversation/get-signed-url",
                    headers=self._get_headers(),
                    params={"agent_id": agent_id},
                )
                response.raise_for_status()
                result = response.json()

            signed_url = result.get("signed_url")
            dashboard_url = "https://elevenlabs.io/app/conversational-ai"
            embed_code = f'<elevenlabs-convai agent-id="{agent_id}"></elevenlabs-convai><script src="https://unpkg.com/@elevenlabs/convai-widget-embed" async type="text/javascript"></script>'

            if open_in_browser:
                webbrowser.open(dashboard_url)
                log_info("Opened agent dashboard in browser")

            return json.dumps(
                {
                    "success": True,
                    "agent_id": agent_id,
                    "signed_url": signed_url,
                    "embed_code": embed_code,
                    "dashboard_url": dashboard_url,
                    "message": f"Agent ID: {agent_id}. Add embed_code to your HTML to start voice chat. Enable 'Public Access' in dashboard first.",
                }
            )

        except Exception as e:
            log_error(f"Failed to get conversation URL: {e}")
            return json.dumps({"error": str(e)})

    async def alist_voices(self) -> str:
        """List available voices (async)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.base_url}/voices", headers=self._get_headers())
                response.raise_for_status()
                result = response.json()

            voices = []
            for voice in result.get("voices", [])[:20]:
                voices.append(
                    {
                        "voice_id": voice.get("voice_id"),
                        "name": voice.get("name"),
                        "category": voice.get("category"),
                        "labels": voice.get("labels", {}),
                    }
                )

            return json.dumps({"success": True, "voices": voices, "total": len(voices)})

        except Exception as e:
            log_error(f"Failed to list voices: {e}")
            return json.dumps({"error": str(e)})

    async def alist_documents(self) -> str:
        """List documents in knowledge base (async)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/convai/knowledge-base", headers=self._get_headers(), params={"page_size": 30}
                )
                response.raise_for_status()
                result = response.json()

            documents = []
            for doc in result.get("documents", []):
                documents.append(
                    {
                        "document_id": doc.get("id"),
                        "name": doc.get("name"),
                        "type": doc.get("type"),
                        "status": doc.get("status"),
                        "created_at": doc.get("created_at_unix_secs"),
                    }
                )

            return json.dumps(
                {
                    "success": True,
                    "documents": documents,
                    "total": len(documents),
                    "uploaded_in_session": self._uploaded_documents,
                }
            )

        except Exception as e:
            log_error(f"Failed to list documents: {e}")
            return json.dumps({"error": str(e)})
