"""Load source metadata for the system prompt."""

import json
from pathlib import Path
from typing import Any

from agno.utils.log import logger

from ..paths import SOURCES_DIR


def load_source_metadata(sources_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load source metadata from JSON files."""
    if sources_dir is None:
        sources_dir = SOURCES_DIR

    sources: list[dict[str, Any]] = []
    if not sources_dir.exists():
        return sources

    for filepath in sorted(sources_dir.glob("*.json")):
        try:
            with open(filepath) as f:
                source = json.load(f)
            sources.append(
                {
                    "source_name": source["source_name"],
                    "source_type": source["source_type"],
                    "description": source.get("description", ""),
                    "content_types": source.get("content_types", []),
                    "capabilities": source.get("capabilities", []),
                    "limitations": source.get("limitations", []),
                    "common_locations": source.get("common_locations", {}),
                    "search_tips": source.get("search_tips", []),
                    "buckets": source.get("buckets", []),  # S3-specific
                }
            )
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.error(f"Failed to load {filepath}: {e}")

    return sources


def build_source_registry(sources_dir: Path | None = None) -> dict[str, Any]:
    """Build source registry from source metadata."""
    sources = load_source_metadata(sources_dir)
    return {
        "sources": sources,
        "source_types": [s["source_type"] for s in sources],
    }


def format_source_registry(registry: dict[str, Any]) -> str:
    """Format source registry for system prompt."""
    lines: list[str] = []

    for source in registry.get("sources", []):
        lines.append(f"### {source['source_name']} (`{source['source_type']}`)")
        if source.get("description"):
            lines.append(source["description"])
        lines.append("")

        # For S3, show buckets prominently
        if source["source_type"] == "s3" and source.get("buckets"):
            lines.append("**Buckets:**")
            for bucket in source["buckets"]:
                lines.append(f"- `{bucket['name']}`: {bucket.get('description', '')}")
                if bucket.get("contains"):
                    lines.append(f"  Contains: {', '.join(bucket['contains'])}")
            lines.append("")

        if source.get("common_locations"):
            lines.append("**Known locations:**")
            for key, value in list(source["common_locations"].items()):
                lines.append(f"- {key}: `{value}`")
            lines.append("")

        if source.get("capabilities"):
            lines.append("**Capabilities:** " + ", ".join(source["capabilities"][:4]))
            lines.append("")

        if source.get("search_tips"):
            lines.append("**Tips:** " + " | ".join(source["search_tips"][:2]))
            lines.append("")

        lines.append("")

    return "\n".join(lines)


SOURCE_REGISTRY = build_source_registry()
SOURCE_REGISTRY_STR = format_source_registry(SOURCE_REGISTRY)
