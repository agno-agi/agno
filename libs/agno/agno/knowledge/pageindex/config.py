from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PageIndexSettings(BaseSettings):
    """Configuration for PageIndex knowledge base.

    All fields can be set via environment variables or passed directly
    to the constructor. Example: ``PAGEINDEX_LLM_PROVIDER=anthropic``.

    Supported LLM providers for indexing:
    - ``openai`` (default) — requires ``OPENAI_API_KEY``
    - ``anthropic`` — requires ``ANTHROPIC_API_KEY`` and ``pip install litellm``
    - ``ollama`` — local, no API key needed
    """

    model_config = SettingsConfigDict(
        env_prefix="PAGEINDEX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Tenant / namespace ---
    tenant_id: str = Field(
        default="default",
        description="Namespace for registry and storage isolation.",
    )

    # --- LLM provider (used for indexing) ---
    llm_provider: Literal["openai", "anthropic", "ollama"] = Field(default="openai")
    model: Optional[str] = Field(
        default=None,
        description="Override model for indexing. Falls back to provider-specific default.",
    )
    openai_model: str = Field(default="gpt-4o-2024-11-20")
    anthropic_model: str = Field(default="claude-sonnet-4-6")
    ollama_model: str = Field(default="qwen2.5:7b")
    ollama_base_url: str = Field(default="http://localhost:11434/v1")
    ollama_api_key: str = Field(default="ollama")

    # --- API keys (not prefixed — read from standard env vars) ---
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")

    # --- Storage ---
    results_dir: Path = Field(default=Path("pageindex_results"))
    upload_dir: Path = Field(default=Path("pageindex_uploads"))

    # --- Retrieval ---
    top_k_nodes: int = Field(default=6, description="Default number of top nodes per retrieval query.")
    min_retrieval_score: int = Field(default=2, description="Minimum keyword score threshold.")
    max_evidence_chars: int = Field(default=9000, description="Max chars per evidence snippet.")

    # --- Caching ---
    structure_cache_size: int = Field(default=256, description="Max cached structure JSONs in memory.")

    # --- Derived ---

    @property
    def active_model(self) -> str:
        if self.model:
            return self.model
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        if self.llm_provider == "ollama":
            return self.ollama_model
        return self.openai_model

    @property
    def tenant_results_dir(self) -> Path:
        return self.results_dir / self.tenant_id

    @property
    def tenant_upload_dir(self) -> Path:
        return self.upload_dir / self.tenant_id

    @property
    def registry_path(self) -> Path:
        return self.tenant_results_dir / "doc_registry.json"

    def prepare_environment(self) -> None:
        """Create directories and propagate API keys to ``os.environ``."""
        self.tenant_results_dir.mkdir(parents=True, exist_ok=True)
        self.tenant_upload_dir.mkdir(parents=True, exist_ok=True)

        if self.llm_provider == "ollama":
            os.environ.setdefault("OPENAI_BASE_URL", self.ollama_base_url)
            os.environ.setdefault("OPENAI_API_KEY", self.ollama_api_key)
            return

        if self.llm_provider == "anthropic":
            resolved_key = self.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
            if resolved_key:
                os.environ.setdefault("ANTHROPIC_API_KEY", resolved_key)
            return

        resolved_key = self.openai_api_key or os.getenv("OPENAI_API_KEY")
        if resolved_key:
            os.environ.setdefault("OPENAI_API_KEY", resolved_key)
