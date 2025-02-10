import json
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from baidusearch.baidusearch import search  # type: ignore
except ImportError:
    raise ImportError("`baidusearch` not installed. Please install using `pip install baidusearch`")

try:
    from pycountry import pycountry
except ImportError:
    raise ImportError("`pycountry` not installed. Please install using `pip install pycountry`")


class BaiduSearchTools(Toolkit):
    """
    BaiduSearch is a toolkit for searching Baidu easily.

    Args:
        fixed_max_results (Optional[int]): A fixed number of maximum results.
        fixed_language (Optional[str]): A fixed language for the search results.
        headers (Optional[Any]): Headers to be used in the search request.
        proxy (Optional[str]): Proxy to be used in the search request.
        debug (Optional[bool]): Enable debug output.
    """

    def __init__(
        self,
        fixed_max_results: Optional[int] = None,
        fixed_language: Optional[str] = None,
        headers: Optional[Any] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 10,
        debug: Optional[bool] = False,
    ):
        super().__init__(name="baidusearch")
        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language
        self.headers = headers
        self.proxy = proxy
        self.timeout = timeout
        self.debug = debug
        self.register(self.baidu_search)

    def baidu_search(self, query: str, max_results: int = 5, language: str = "zh") -> str:
        """Execute Baidu search and return results

        Args:
            query (str): Search keyword
            max_results (int, optional): Maximum number of results to return, default 5
            language (str, optional): Search language, default Chinese

        Returns:
            str: A JSON formatted string containing the search results.
        """
        max_results = self.fixed_max_results or max_results
        language = self.fixed_language or language

        if len(language) != 2:
            try:
                language = pycountry.languages.lookup(language).alpha_2
            except LookupError:
                language = "zh"

        logger.debug(f"Searching Baidu [{language}] for: {query}")

        results = search(keyword=query, num_results=max_results)

        res: List[Dict[str, str]] = []
        for idx, item in enumerate(results, 1):
            res.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "abstract": item.get("abstract", ""),
                    "rank": str(idx),
                }
            )
        return json.dumps(res, indent=2)
