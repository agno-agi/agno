import json
import urllib.parse
from typing import List, Optional

import httpx

from agno.tools.toolkit import Toolkit
from agno.utils.log import log_info


class Searxng(Toolkit):
    def __init__(
        self,
        host: str,
        engines: List[str] = [],
        fixed_max_results: Optional[int] = None,
        images: bool = False,
        it: bool = False,
        map: bool = False,
        music: bool = False,
        news: bool = False,
        science: bool = False,
        videos: bool = False,
        **kwargs,
    ):
        super().__init__(name="searxng", **kwargs)

        self.host = host
        self.engines = engines
        self.fixed_max_results = fixed_max_results

        self.register(self.search)

        if images:
            self.register(self.image_search)
        if it:
            self.register(self.it_search)
        if map:
            self.register(self.map_search)
        if music:
            self.register(self.music_search)
        if news:
            self.register(self.news_search)
        if science:
            self.register(self.science_search)
        if videos:
            self.register(self.video_search)

    def search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search the web.

        Args:
            query (str): The query to search the web with.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.

        Returns:
            The results of the search.
        """
        return self._search(query, max_results=max_results)

    def image_search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search for images.

        Args:
            query (str): The query to search images with.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.

        Returns:
            The results of the search.
        """
        return self._search(query, "images", max_results)

    def it_search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search for IT related information.

        Args:
            query (str): The query to search for IT related information.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.

        Returns:
            The results of the search.
        """
        return self._search(query, "it", max_results)

    def map_search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search maps

        Args:
            query (str): The query to search maps with.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.

        Returns:
            The results of the search.
        """
        return self._search(query, "map", max_results)

    def music_search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search for information related to music.

        Args:
            query (str): The query to search music with.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.

        Returns:
            The results of the search.
        """
        return self._search(query, "music", max_results)

    def news_search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search for news.

        Args:
            query (str): The query to search news with.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.

        Returns:
            The results of the search.
        """
        return self._search(query, "news", max_results)

    def science_search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search for information related to science.

        Args:
            query (str): The query to search science with.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.

        Returns:
            The results of the search.
        """
        return self._search(query, "science", max_results)

    def video_search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search for videos.

        Args:
            query (str): The query to search videos with.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.

        Returns:
            The results of the search.
        """
        return self._search(query, "videos", max_results)

    def _search(self, query: str, category: Optional[str] = None, max_results: int = 5) -> str:
        encoded_query = urllib.parse.quote(query)
        url = f"{self.host}/search?format=json&q={encoded_query}"

        if self.engines:
            url += f"&engines={','.join(self.engines)}"
        if category:
            url += f"&categories={category}"

        log_info(f"Fetching results from searxng: {url}")
        try:
            resp = httpx.get(url).json()
            results = self.fixed_max_results or max_results
            resp["results"] = resp["results"][:results]
            return json.dumps(resp)
        except Exception as e:
            return f"Error fetching results from searxng: {e}"
