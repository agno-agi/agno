import json
from os import getenv
from typing import Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_debug


class SerperApiTools(Toolkit):
    """
    A class to interact with the Serper API for Google search functionality. Go to serper.dev for more information.

    Attributes:
        api_key (str): The API key for accessing the Serper API.
        location (str): The Google search location to be used for the search (default is "us").
        num_results (int): The number of search results to return (default is 10).

    Methods:
        search_google(query: str, gl: Optional[str] = None) -> str:
            Performs a Google search using the Serper API and returns the results.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        location: str = "us",
        num_results: int = 10,
    ):
        """
        Initializes the SerperApiTools instance.

        Args:
            api_key (str, optional): The Serper API key. If not provided, will be fetched from the environment variable "SERPER_API_KEY".
            gl (str, optional): The Google location code for search results (default is "us").
            num_results (int, optional): The number of search results to retrieve (default is 10).
        """
        super().__init__(name="serper_api_tools")

        self.api_key = api_key or getenv("SERPER_API_KEY")
        if not self.api_key:
            log_debug("No Serper API key provided")

        self.location = location
        self.num_results = num_results
        self.register(self.search_google)

    def search_google(self, query: str, location: Optional[str] = None) -> str:
        """
        Searches Google for the provided query using the Serper API.

        Args:
            query (str): The search query to search for on Google.
            location (str, optional): The Google location code for search results. If not provided, the default class attribute is used.

        Returns:
            str: The search results in JSON format or an error message if the search fails.
        """
        try:
            if not self.api_key:
                return "Please provide an API key"
            if not query:
                return "Please provide a query to search for"

            log_debug(f"Searching Google for: {query}")

            url = "https://google.serper.dev/search"
            headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
            # Use the gl parameter from the method if provided, otherwise use the class attribute
            search_gl = location if location is not None else self.location
            params = {"q": query, "num": self.num_results, "gl": search_gl}
            payload = json.dumps(params)
            response = requests.request("POST", url, headers=headers, data=payload)
            results = response.text

            return results

        except Exception as e:
            return f"Error searching for the query {query}: {e}"
