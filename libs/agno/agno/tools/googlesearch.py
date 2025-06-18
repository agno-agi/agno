import json
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from googlesearch import search
except ImportError:
    raise ImportError("`googlesearch-python` not installed. Please install using `pip install googlesearch-python`")

try:
    from pycountry import pycountry
except ImportError:
    raise ImportError("`pycountry` not installed. Please install using `pip install pycountry`")


class GoogleSearchTools(Toolkit):
    """
    GoogleSearch is a Python library for searching Google easily.
    It uses requests and BeautifulSoup4 to scrape Google.

    Args:
        fixed_max_results (Optional[int]): A fixed number of maximum results.
        fixed_language (Optional[str]): Language of the search results.
        headers (Optional[Any]): Custom headers for the request.
        proxy (Optional[str]): Proxy settings for the request.
        timeout (Optional[int]): Timeout for the request, default is 10 seconds.
        cache_results (bool): Enable caching of search results.
        cache_ttl (int): Time-to-live for cached results in seconds.
        cache_dir (Optional[str]): Directory to store cache files.
    """

    def __init__(
        self,
        fixed_max_results: Optional[int] = None,
        fixed_language: Optional[str] = None,
        headers: Optional[Any] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 10,
        **kwargs,
    ):
        self.fixed_max_results: Optional[int] = fixed_max_results
        self.fixed_language: Optional[str] = fixed_language
        self.headers: Optional[Any] = headers
        self.proxy: Optional[str] = proxy
        self.timeout: Optional[int] = timeout

        tools = []
        tools.append(self.google_search)

        super().__init__(name="google_search_tools", tools=tools, **kwargs)

    def google_search(self, query: str, max_results: int = 5, language: str = "en") -> str:
        """
        Use this function to search Google for a specified query.

        Args:
            query (str): The query to search for.
            max_results (int, optional): The maximum number of results to return. Default is 5.
            language (str, optional): The language of the search results. Default is "en".

        Returns:
            str: A JSON formatted string containing the search results.
        """
        max_results = self.fixed_max_results or max_results
        language = self.fixed_language or language

        # Resolve language to ISO 639-1 code if needed
        if len(language) != 2:
            _language = pycountry.languages.lookup(language)
            if _language:
                language = _language.alpha_2
            else:
                language = "en"

        log_debug(f"Searching Google [{language}] for: {query}")

        # Perform Google search using the googlesearch-python package
        results = list(search(query, num_results=max_results, lang=language, proxy=self.proxy, advanced=True))

        # Collect the search results
        res: List[Dict[str, str]] = []
        for result in results:
            res.append(
                {
                    "title": result.title,
                    "url": result.url,
                    "description": result.description,
                }
            )

        return json.dumps(res, indent=2)
