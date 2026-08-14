import json
import warnings
from typing import Any, Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

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
        baidu_search: bool = True,
        all: bool = False,
        **kwargs,
    ):
        # Backwards compat for old param names
        if "enable_baidu_search" in kwargs:
            warnings.warn("enable_baidu_search is deprecated, use baidu_search", DeprecationWarning, stacklevel=2)
            baidu_search = kwargs.pop("enable_baidu_search")

        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language
        self.headers = headers
        self.proxy = proxy
        self.timeout = timeout
        self.debug = debug

        tools: List[Callable] = []
        if all or baidu_search:
            tools.append(self.baidu_search)

        super().__init__(name="baidu_search_tools", tools=tools, **kwargs)

    def baidu_search(self, query: str, max_results: int = 5, language: str = "zh") -> str:
        """Execute Baidu search and return results.

        Args:
            query: Search keyword.
            max_results: Maximum number of results to return. Defaults to 5.
            language: Search language code. Defaults to "zh" (Chinese).

        Returns:
            JSON with list of search results containing title, url, abstract, rank.
        """
        max_results = self.fixed_max_results or max_results
        language = self.fixed_language or language

        if len(language) != 2:
            try:
                language = pycountry.languages.lookup(language).alpha_2
            except LookupError:
                language = "zh"

        log_debug(f"Searching Baidu [{language}] for: {query}")

        try:
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
            return json.dumps(res)
        except Exception as e:
            return json.dumps({"error": f"Baidu search failed: {e}"})
