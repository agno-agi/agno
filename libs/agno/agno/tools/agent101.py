import json
import urllib.request
import urllib.parse
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import log_info, logger


class Agent101Tools(Toolkit):
    """Agent101 is a toolkit for discovering AI agent tools and capabilities.

    It provides functions to search for tools, list categories, and get
    recommendations for a given task via the Agent101 API.

    No extra dependencies are required as it uses urllib from the standard library.

    Args:
        base_url (str, optional): The base URL of the Agent101 API.
            Defaults to "https://agent101.ventify.ai/api".
        timeout (int, optional): Request timeout in seconds. Defaults to 30.
    """

    def __init__(
        self,
        base_url: str = "https://agent101.ventify.ai/api",
        timeout: int = 30,
        enable_search_tools: bool = True,
        enable_list_categories: bool = True,
        enable_recommend: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        tools = []
        if all or enable_search_tools:
            tools.append(self.search_tools)
        if all or enable_list_categories:
            tools.append(self.list_categories)
        if all or enable_recommend:
            tools.append(self.recommend)

        super().__init__(name="agent101", tools=tools, **kwargs)

    def _request(self, url: str) -> str:
        """Make an HTTP GET request and return the response body as a string.

        Args:
            url (str): The full URL to request.

        Returns:
            str: The response body.
        """
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except Exception as e:
            logger.error(f"Agent101 API request failed: {e}")
            return json.dumps({"error": str(e)})

    def search_tools(self, query: str) -> str:
        """Search the Agent101 directory for AI agent tools matching a query.

        Use this function to find tools, integrations, and capabilities available
        for AI agents based on a keyword or description.

        Args:
            query (str): The search query describing the tools to look for.

        Returns:
            str: A JSON string containing the matching tools.
        """
        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_info(f"Searching Agent101 for: {query}")
        encoded_query = urllib.parse.quote(query)
        url = f"{self.base_url}/search?q={encoded_query}"
        return self._request(url)

    def list_categories(self) -> str:
        """List all available tool categories in the Agent101 directory.

        Use this function to discover what categories of AI agent tools are available.

        Returns:
            str: A JSON string containing the list of categories.
        """
        log_info("Listing Agent101 categories")
        url = f"{self.base_url}/categories"
        return self._request(url)

    def recommend(self, task: str) -> str:
        """Get tool recommendations from Agent101 for a specific task.

        Use this function to get AI agent tool recommendations based on a task description.

        Args:
            task (str): A description of the task to get recommendations for.

        Returns:
            str: A JSON string containing recommended tools for the task.
        """
        if not task:
            return json.dumps({"error": "Please provide a task description"})

        log_info(f"Getting Agent101 recommendations for: {task}")
        encoded_task = urllib.parse.quote(task)
        url = f"{self.base_url}/recommend?task={encoded_task}"
        return self._request(url)
