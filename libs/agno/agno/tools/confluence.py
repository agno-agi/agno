import json
from os import getenv
from typing import Callable, List, Optional

import requests

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
        get_page_content: bool = True,
        get_space_key: bool = True,
        get_all_space_detail: bool = True,
        get_all_page_from_space: bool = True,
        create_page: bool = False,
        update_page: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize Confluence Tools for interacting with Confluence pages and spaces.

        Args:
            username: Confluence username. Falls back to CONFLUENCE_USERNAME env var.
            password: Confluence password. Falls back to CONFLUENCE_PASSWORD env var.
            url: Confluence instance URL. Falls back to CONFLUENCE_URL env var.
            api_key: Confluence API key. Falls back to CONFLUENCE_API_KEY env var.
            verify_ssl: Verify SSL certificates. Defaults to True.
            get_page_content: Enable get_page_content tool. Defaults to True.
            get_space_key: Enable get_space_key tool. Defaults to True.
            get_all_space_detail: Enable get_all_space_detail tool. Defaults to True (token heavy).
            get_all_page_from_space: Enable get_all_page_from_space tool. Defaults to True (token heavy).
            create_page: Enable create_page tool. Defaults to False (creates external content).
            update_page: Enable update_page tool. Defaults to False (modifies external content).
            all: Enable all tools. Defaults to False.
        """

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

        session = requests.Session()
        session.verify = verify_ssl

        if not verify_ssl:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.confluence = Confluence(
            url=self.url,
            username=self.username,
            password=self.password,
            verify_ssl=verify_ssl,
            session=session,
        )

        tools: List[Callable] = []
        if all or get_page_content:
            tools.append(self.get_page_content)
        if all or get_space_key:
            tools.append(self.get_space_key)
        if all or get_all_space_detail:
            tools.append(self.get_all_space_detail)
        if all or get_all_page_from_space:
            tools.append(self.get_all_page_from_space)
        if all or create_page:
            tools.append(self.create_page)
        if all or update_page:
            tools.append(self.update_page)

        super().__init__(name="confluence_tools", tools=tools, **kwargs)

    def get_page_content(self, space_name: str, page_title: str, expand: Optional[str] = "body.storage") -> str:
        """Retrieve the content of a specific page in a Confluence space.

        Args:
            space_name: Name of the Confluence space.
            page_title: Title of the page to retrieve.
            expand: Fields to expand in the page response. Defaults to "body.storage".

        Returns:
            str: JSON-encoded page content or error message.
        """
        try:
            log_info(f"Retrieving page content from space '{space_name}'")
            key = self._get_space_key_internal(space_name)
            if key is None:
                return json.dumps({"error": f"Space '{space_name}' not found"})

            page = self.confluence.get_page_by_title(key, page_title, expand=expand)
            if page:
                log_info(f"Successfully retrieved page '{page_title}' from space '{space_name}'")
                return json.dumps(page)

            logger.warning(f"Page '{page_title}' not found in space '{space_name}'")
            return json.dumps({"error": f"Page '{page_title}' not found in space '{space_name}'"})

        except Exception as e:
            logger.exception(f"Error retrieving page '{page_title}'")
            return json.dumps({"error": str(e)})

    def get_all_space_detail(self) -> str:
        """Retrieve details about all Confluence spaces.

        Returns:
            str: JSON-encoded list of space details.
        """
        log_info("Retrieving details for all Confluence spaces")
        results = []
        start = 0
        limit = 50

        try:
            while True:
                spaces_data = self.confluence.get_all_spaces(start=start, limit=limit)
                if not spaces_data.get("results"):
                    break
                results.extend(spaces_data["results"])

                if len(spaces_data["results"]) < limit:
                    break
                start += limit

            return json.dumps(results)
        except Exception as e:
            logger.exception("Error retrieving all spaces")
            return json.dumps({"error": str(e)})

    def _get_space_key_internal(self, space_name: str) -> Optional[str]:
        """Internal helper to get space key. Returns None if not found."""
        start = 0
        limit = 50

        while True:
            result = self.confluence.get_all_spaces(start=start, limit=limit)
            if not result.get("results"):
                break

            spaces = result["results"]

            for space in spaces:
                if space["name"].lower() == space_name.lower():
                    log_info(f"Found space key for '{space_name}': {space['key']}")
                    return space["key"]

            for space in spaces:
                if space["key"] == space_name:
                    log_info(f"'{space_name}' is already a space key")
                    return space_name

            if len(spaces) < limit:
                break
            start += limit

        logger.warning(f"No space named {space_name} found")
        return None

    def get_space_key(self, space_name: str) -> str:
        """Get the space key for a particular Confluence space.

        Args:
            space_name: Name of the space whose key is required.

        Returns:
            str: JSON-encoded space key or error message.
        """
        try:
            key = self._get_space_key_internal(space_name)
            if key is None:
                return json.dumps({"error": f"No space found with name '{space_name}'"})
            return json.dumps({"key": key})
        except Exception as e:
            logger.exception(f"Error finding space key for '{space_name}'")
            return json.dumps({"error": str(e)})

    def get_all_page_from_space(self, space_name: str) -> str:
        """Retrieve all pages from a specific Confluence space.

        Args:
            space_name: Name of the Confluence space.

        Returns:
            str: JSON-encoded list of page details.
        """
        try:
            log_info(f"Retrieving all pages from space '{space_name}'")
            space_key = self._get_space_key_internal(space_name)

            if space_key is None:
                return json.dumps({"error": f"Space '{space_name}' not found"})

            page_details = self.confluence.get_all_pages_from_space(
                space_key, status=None, expand=None, content_type="page"
            )

            if not page_details:
                return json.dumps({"error": f"No pages found in space '{space_name}'"})

            return json.dumps([{"id": page["id"], "title": page["title"]} for page in page_details])
        except Exception as e:
            logger.exception(f"Error retrieving pages from space '{space_name}'")
            return json.dumps({"error": str(e)})

    def create_page(self, space_name: str, title: str, body: str, parent_id: Optional[str] = None) -> str:
        """Create a new page in Confluence.

        Args:
            space_name: Name of the Confluence space.
            title: Title of the new page.
            body: Content of the new page.
            parent_id: ID of the parent page if creating a child page. Defaults to None.

        Returns:
            str: JSON-encoded page ID and title or error message.
        """
        try:
            space_key = self._get_space_key_internal(space_name)
            if space_key is None:
                return json.dumps({"error": f"Space '{space_name}' not found"})

            page = self.confluence.create_page(space_key, title, body, parent_id=parent_id)
            log_info(f"Page created: {title} with ID {page['id']}")
            return json.dumps({"id": page["id"], "title": title})
        except Exception as e:
            logger.exception(f"Error creating page '{title}'")
            return json.dumps({"error": str(e)})

    def update_page(self, page_id: str, title: str, body: str) -> str:
        """Update an existing Confluence page.

        Args:
            page_id: ID of the page to update.
            title: New title for the page.
            body: Updated content for the page.

        Returns:
            str: JSON-encoded status and ID of the updated page or error message.
        """
        try:
            updated_page = self.confluence.update_page(page_id, title, body)
            log_info(f"Page updated: {title} with ID {updated_page['id']}")
            return json.dumps({"status": "success", "id": updated_page["id"]})
        except Exception as e:
            logger.exception(f"Error updating page '{title}'")
            return json.dumps({"error": str(e)})
