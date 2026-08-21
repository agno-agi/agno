import json
import os
from typing import Any, Callable, Dict, List, Optional, cast

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from notion_client import Client
except ImportError:
    raise ImportError("`notion-client` not installed. Please install using `pip install notion-client`")


class NotionTools(Toolkit):
    """Notion toolkit for creating and managing Notion pages.

    Args:
        api_key: Notion API key (integration token). If not provided, uses NOTION_API_KEY env var.
        database_id: The ID of the database to work with. If not provided, uses NOTION_DATABASE_ID env var.
        search_pages: Register the search_pages tool (read operation).
        create_page: Register the create_page tool (write operation).
        update_page: Register the update_page tool (write operation).
        all: Register all tools regardless of individual flags.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        database_id: Optional[str] = None,
        search_pages: bool = True,
        create_page: bool = False,
        update_page: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        self.api_key = api_key or os.getenv("NOTION_API_KEY")
        self.database_id = database_id or os.getenv("NOTION_DATABASE_ID")

        if not self.api_key:
            raise ValueError(
                "Notion API key is required. Either pass api_key parameter or set NOTION_API_KEY environment variable."
            )
        if not self.database_id:
            raise ValueError(
                "Notion database ID is required. Either pass database_id parameter or set NOTION_DATABASE_ID environment variable."
            )

        self.client = Client(auth=self.api_key)

        tools: List[Callable] = []
        if all or search_pages:
            tools.append(self.search_pages)
        if all or create_page:
            tools.append(self.create_page)
        if all or update_page:
            tools.append(self.update_page)

        super().__init__(name="notion_tools", tools=tools, **kwargs)

    def create_page(self, title: str, tag: str, content: str) -> str:
        """Create a new page in the Notion database with a title, tag, and content.

        Args:
            title: The title of the page.
            tag: The tag/category for the page (e.g., travel, tech, general-blogs, fashion, documents).
            content: The content to add to the page.

        Returns:
            JSON object with page_id, url, title, tag, and success status.
        """
        try:
            log_debug(f"Creating Notion page with title: {title}, tag: {tag}")

            # Create the page in the database
            new_page = cast(
                Dict[str, Any],
                self.client.pages.create(
                    parent={"database_id": self.database_id},
                    properties={"Name": {"title": [{"text": {"content": title}}]}, "Tag": {"select": {"name": tag}}},
                    children=[
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
                        }
                    ],
                ),
            )

            return json.dumps(
                {"success": True, "page_id": new_page["id"], "url": new_page["url"], "title": title, "tag": tag}
            )

        except Exception as e:
            logger.exception(e)
            return json.dumps({"success": False, "error": str(e)})

    def update_page(self, page_id: str, content: str) -> str:
        """Add content to an existing Notion page.

        Args:
            page_id: The ID of the page to update.
            content: The content to append to the page.

        Returns:
            JSON object with page_id, message, and success status.
        """
        try:
            log_debug(f"Updating Notion page: {page_id}")

            # Append content to the page
            self.client.blocks.children.append(
                block_id=page_id,
                children=[
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
                    }
                ],
            )

            return json.dumps({"success": True, "page_id": page_id, "message": "Content added successfully"})

        except Exception as e:
            logger.exception(e)
            return json.dumps({"success": False, "error": str(e)})

    def search_pages(self, tag: str) -> str:
        """Search for pages in the database by tag.

        Args:
            tag: The tag to search for.

        Returns:
            JSON object with count, pages array (page_id, title, tag, url), and success status.
        """
        try:
            log_debug(f"Searching for pages with tag: {tag}")

            # The SDK's DatabasesEndpoint does not have a query method, use client.request
            data = cast(
                Dict[str, Any],
                self.client.request(
                    path=f"databases/{self.database_id}/query",
                    method="POST",
                    body={"filter": {"property": "Tag", "select": {"equals": tag}}},
                ),
            )

            pages = []
            for page in data.get("results", []):
                try:
                    page_title = "Untitled"
                    if page.get("properties", {}).get("Name", {}).get("title"):
                        page_title = page["properties"]["Name"]["title"][0]["text"]["content"]

                    page_tag = None
                    if page.get("properties", {}).get("Tag", {}).get("select"):
                        page_tag = page["properties"]["Tag"]["select"]["name"]

                    page_info = {
                        "page_id": page["id"],
                        "title": page_title,
                        "tag": page_tag,
                        "url": page.get("url", ""),
                    }
                    pages.append(page_info)
                except Exception as page_error:
                    log_debug(f"Error parsing page: {page_error}")
                    continue

            return json.dumps({"success": True, "count": len(pages), "pages": pages})

        except Exception as e:
            logger.exception(e)
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "message": "Failed to search pages. Make sure the database is shared with the integration and has a 'Tag' property.",
                }
            )
