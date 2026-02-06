"""Base connector interface for all knowledge sources."""

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Abstract base class for all knowledge source connectors."""

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the source type identifier (e.g., 'google_drive', 'notion', 'slack')."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the human-readable source name."""

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authenticate with the source.

        Returns:
            True if authentication successful, False otherwise.
        """

    @abstractmethod
    def list_items(
        self,
        parent_id: str | None = None,
        item_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        List items in the source.

        Args:
            parent_id: Parent container ID (folder, workspace, channel)
            item_type: Filter by item type
            limit: Maximum items to return

        Returns:
            List of item dictionaries with at minimum 'id', 'name', 'type' fields.
        """

    @abstractmethod
    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Search for content in the source.

        Args:
            query: Search query string
            filters: Optional filters (e.g., file type, date range, author)
            limit: Maximum results to return

        Returns:
            List of search result dictionaries.
        """

    @abstractmethod
    def read(
        self,
        item_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Read content from a specific item.

        Args:
            item_id: The item identifier
            options: Optional read options (e.g., page range, include_metadata)

        Returns:
            Dictionary with 'content', 'metadata', and source-specific fields.
        """

    @abstractmethod
    def write(
        self,
        parent_id: str,
        title: str,
        content: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create new content in the source.

        Args:
            parent_id: Parent container ID
            title: Title/name for the new content
            content: The content to write
            options: Optional write options

        Returns:
            Dictionary with created item info including 'id'.
        """

    @abstractmethod
    def update(
        self,
        item_id: str,
        content: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Update existing content.

        Args:
            item_id: The item to update
            content: New content (if updating content)
            properties: Properties to update (e.g., title, metadata)

        Returns:
            Dictionary with updated item info.
        """
