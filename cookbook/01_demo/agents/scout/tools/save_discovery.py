"""Save successful discoveries to knowledge base."""

import json

from agno.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.tools import tool
from agno.utils.log import logger


def create_save_intent_discovery_tool(knowledge: Knowledge):
    """Create save_intent_discovery tool with knowledge injected."""

    @tool
    def save_intent_discovery(
        name: str,
        intent: str,
        location: str,
        source: str,
        summary: str | None = None,
        search_terms: list[str] | None = None,
    ) -> str:
        """Save a successful discovery to knowledge base for future reference.

        Call this after successfully finding information that might be useful for similar
        future queries. This helps Scout learn where information is typically found.

        Args:
            name: Short name for this discovery (e.g., "q4_okrs_location")
            intent: What the user was looking for (e.g., "Find Q4 OKRs")
            location: Where the information was found (e.g., "s3://company-docs/policies/handbook.md")
            source: Which source type (s3)
            summary: Brief description of what was found
            search_terms: Search terms that worked to find this
        """
        if not name or not name.strip():
            return "Error: Name required."
        if not intent or not intent.strip():
            return "Error: Intent required."
        if not location or not location.strip():
            return "Error: Location required."
        if not source or not source.strip():
            return "Error: Source required."

        valid_sources = ["s3"]
        if source.lower() not in valid_sources:
            return f"Error: Source must be one of: {', '.join(valid_sources)}"

        payload = {
            "type": "intent_discovery",
            "name": name.strip(),
            "intent": intent.strip(),
            "location": location.strip(),
            "source": source.strip().lower(),
            "summary": summary.strip() if summary else None,
            "search_terms": search_terms or [],
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            knowledge.insert(
                name=name.strip(),
                text_content=json.dumps(payload, ensure_ascii=False, indent=2),
                reader=TextReader(),
                skip_if_exists=True,
            )
            return f"Saved discovery '{name}' to knowledge base."
        except (AttributeError, TypeError, ValueError, OSError) as e:
            logger.error(f"Failed to save discovery: {e}")
            return f"Error: {e}"

    return save_intent_discovery
