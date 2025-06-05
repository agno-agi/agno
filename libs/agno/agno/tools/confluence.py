import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

try:
    from atlassian import Confluence
except (ModuleNotFoundError, ImportError):
    raise ImportError("atlassian-python-api not install . Please install using `pip install atlassian-python-api`")


class ConfluenceTools(Toolkit):
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        verify_ssl: bool = True,
        **kwargs,
    ):
        """Initialize Confluence Tools with authentication credentials.

        Args:
            username (str, optional): Confluence username. Defaults to None.
            password (str, optional): Confluence password. Defaults to None.
            url (str, optional): Confluence instance URL. Defaults to None.
            api_key (str, optional): Confluence API key. Defaults to None.
            verify_ssl (bool, optional): Whether to verify SSL certificates. Defaults to True.

        Notes:
            Credentials can be provided either through method arguments or environment variables:
            - CONFLUENCE_URL
            - CONFLUENCE_USERNAME
            - CONFLUENCE_API_KEY
        """

        super().__init__(name="confluence_tools", **kwargs)
        self.url = url or getenv("CONFLUENCE_URL")
        self.username = username or getenv("CONFLUENCE_USERNAME")
        self.password = api_key or getenv("CONFLUENCE_API_KEY") or password or getenv("CONFLUENCE_PASSWORD")

        if not self.url:
            raise ValueError(
                "Confluence URL not provided. Pass it in the constructor or set CONFLUENCE_URL in environment variable"
            )

        if not self.username:
            raise ValueError(
                "Confluence username not provided. Pass it in the constructor or set CONFLUENCE_USERNAME in environment variable"
            )

        if not self.password:
            raise ValueError("Confluence API KEY or password not provided")

        self.confluence = Confluence(
            url=self.url, username=self.username, password=self.password, verify_ssl=verify_ssl
        )
        if not verify_ssl:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        tools: List[Any] = []
        tools.append(self.get_page_content)
        tools.append(self.get_space_key)
        tools.append(self.create_page)
        tools.append(self.update_page)
        tools.append(self.get_all_space_detail)
        tools.append(self.get_all_page_from_space)

        super().__init__(name="confluence_tools", tools=tools, **kwargs)

    def get_page_content(self, space_name: str, page_title: str, expand: Optional[str] = "body.storage"):
        """Retrieve the content of a specific page in a Confluence space.

        Args:
            space_name (str): Name of the Confluence space.
            page_title (str): Title of the page to retrieve.
            expand (str, optional): Fields to expand in the page response. Defaults to "body.storage".

        Returns:
            str: JSON-encoded page content or error message.
        """
        try:
            log_info(f"Retrieving page content from space '{space_name}'")
            key = self.get_space_key(space_name=space_name)
            page = self.confluence.get_page_by_title(key, page_title, expand=expand)
            if page:
                log_info(f"Successfully retrieved page '{page_title}' from space '{space_name}'")
                return json.dumps(page)

            logger.warning(f"Page '{page_title}' not found in space '{space_name}'")
            return json.dumps({"error": f"Page '{page_title}' not found in space '{space_name}'"})

        except Exception as e:
            logger.error(f"Error retrieving page '{page_title}': {e}")
            return json.dumps({"error": str(e)})

    def get_all_space_detail(self):
        """Retrieve details about all Confluence spaces.

        Returns:
            str: List of space details as a string.
        """
        log_info("Retrieving details for all Confluence spaces")
        results = self.confluence.get_all_spaces()["results"]
        return str(results)

    def get_space_key(self, space_name: str):
        """Get the space key for a particular Confluence space.

        Args:
            space_name (str): Name of the space whose key is required.

        Returns:
            str: Space key or "No space found" if space doesn't exist.
        """
        result = self.confluence.get_all_spaces()
        spaces = result["results"]

        for space in spaces:
            if space["name"] == space_name:
                log_info(f"Found space key for '{space_name}'")
                return space["key"]

        logger.warning(f"No space named {space_name} found")
        return "No space found"

    def get_all_page_from_space(self, space_name: str):
        """Retrieve all pages from a specific Confluence space.

        Args:
            space_name (str): Name of the Confluence space.

        Returns:
            list: Details of pages in the specified space.
        """
        log_info(f"Retrieving all pages from space '{space_name}'")
        space_key = self.get_space_key(space_name)
        page_details = self.confluence.get_all_pages_from_space(
            space_key, status=None, expand=None, content_type="page"
        )
        page_details = str([{"id": page["id"], "title": page["title"]} for page in page_details])
        return page_details

    def create_page(self, space_name: str, title: str, body: str, parent_id: Optional[str] = None) -> str:
        """Create a new page in Confluence.

        Args:
            space_name (str): Name of the Confluence space.
            title (str): Title of the new page.
            body (str): Content of the new page.
            parent_id (str, optional): ID of the parent page if creating a child page. Defaults to None.

        Returns:
            str: JSON-encoded page ID and title or error message.
        """
        try:
            space_key = self.get_space_key(space_name=space_name)
            page = self.confluence.create_page(space_key, title, body, parent_id=parent_id)
            log_info(f"Page created: {title} with ID {page['id']}")
            return json.dumps({"id": page["id"], "title": title})
        except Exception as e:
            logger.error(f"Error creating page '{title}': {e}")
            return json.dumps({"error": str(e)})

    def update_page(self, page_id: str, title: str, body: str) -> str:
        """Update an existing Confluence page.

        Args:
            page_id (str): ID of the page to update.
            title (str): New title for the page.
            body (str): Updated content for the page.

        Returns:
            str: JSON-encoded status and ID of the updated page or error message.
        """
        try:
            updated_page = self.confluence.update_page(page_id, title, body)
            log_info(f"Page updated: {title} with ID {updated_page['id']}")
            return json.dumps({"status": "success", "id": updated_page["id"]})
        except Exception as e:
            logger.error(f"Error updating page '{title}': {e}")
            return json.dumps({"error": str(e)})
