import json
import asyncio
from os import getenv
from typing import Optional
from agno.tools import Toolkit
from agno.utils.log import log_info

try:
    from brave_search_python_client import (
        BraveSearch,
        WebSearchRequest,
        NewsSearchRequest,
        VideosSearchRequest,
        ImagesSearchRequest,
    )
except ImportError:
    raise ImportError(
        "`brave-search-python-client` not installed. "
        "Please install using `poetry add brave-search-python-client`"
    )


class BraveSearchTools(Toolkit):
    """
    Complete Brave Search toolkit with all new (2025) features.
    
    This toolkit provides access to Brave's independent search index with privacy-preserving
    search capabilities using the official brave-search-python-client.
    
    Features:
    - Web, news, video, and image search (dedicated endpoints)
    - Sync/async support for compatibility with Agno agents
    - Freshness filters for time-based results
    - Safe search content filtering
    - Spellcheck support (plan-dependent)
    - Country and language localization
    
    Args:
        api_key (str, optional): Brave API key. If not provided, uses BRAVE_API_KEY environment variable.
        fixed_max_results (Optional[int]): Fixed maximum results for all searches.
        fixed_language (Optional[str]): Fixed language code for all searches (e.g., 'en', 'es', 'fr').
        fixed_country (Optional[str]): Fixed country code for all searches (e.g., 'US', 'GB', 'DE').
        enable_web_search (bool): Enable main web search tool. Default: True.
        enable_news_search (bool): Enable dedicated news search tool. Default: False.
        enable_video_search (bool): Enable dedicated video search tool. Default: False.
        enable_image_search (bool): Enable image search tool. Default: False.
        all (bool): Enable all available tools. Default: False.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        fixed_language: Optional[str] = None,
        fixed_country: Optional[str] = None,
        enable_web_search: bool = True,
        enable_news_search: bool = False,
        enable_video_search: bool = False,
        enable_image_search: bool = False,
        all: bool = False,
        **kwargs,
    ):
        # Load API key from parameter or environment variable
        self.api_key = api_key or getenv("BRAVE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "BRAVE_API_KEY is required. Please set the BRAVE_API_KEY environment variable."
            )
        
        # Store fixed parameters that will override per-call parameters
        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language
        self.fixed_country = fixed_country
        
        # Initialize the Brave Search client (async by default)
        self.brave_client = BraveSearch(api_key=self.api_key)
        
        # Build tools list based on enabled features
        # Use SYNC wrappers for Agno compatibility
        tools = []
        if all or enable_web_search:
            tools.append(self.brave_search)
        if all or enable_news_search:
            tools.append(self.brave_news_search)
        if all or enable_video_search:
            tools.append(self.brave_video_search)
        if all or enable_image_search:
            tools.append(self.brave_image_search)
        
        # Initialize parent Toolkit with configured tools
        super().__init__(name="brave_search", tools=tools, **kwargs)
    
    def _get_params(self, max_results: int, country: Optional[str], search_lang: Optional[str]) -> dict:
        """
        Helper method to resolve final parameters.
        
        If fixed parameters are set in __init__, they override per-call parameters.
        Otherwise, uses per-call parameters or defaults.
        
        Args:
            max_results: Requested max results
            country: Requested country code
            search_lang: Requested language code
            
        Returns:
            dict: Resolved parameters with keys 'max_results', 'search_lang', 'country'
        """
        return {
            "max_results": self.fixed_max_results if self.fixed_max_results is not None else max_results,
            "search_lang": self.fixed_language if self.fixed_language is not None else (search_lang or "en"),
            "country": self.fixed_country if self.fixed_country is not None else (country or "US"),
        }
    
    
    def brave_search(
        self,
        query: str,
        max_results: int = 5,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        safesearch: str = "moderate",
        freshness: Optional[str] = None,
        spellcheck: bool = False,
    ) -> str:
        """
        Main Brave web search with comprehensive results (SYNC wrapper).
        
        This method wraps the async implementation to work with agent.run().
        For async usage with agent.arun(), use brave_search_async().
        
        Args:
            query (str): The search query term. Maximum 400 characters and 50 words.
            max_results (int, optional): Maximum number of results to return. 
                                        Range: 1-20. Default: 5. API enforces max of 20.
            country (str, optional): Country code for localized results (e.g., 'US', 'GB', 'DE'). 
                                    Uses fixed_country if set, otherwise defaults to 'US'.
            search_lang (str, optional): Language code for results (e.g., 'en', 'es', 'fr'). 
                                        Uses fixed_language if set, otherwise defaults to 'en'.
            safesearch (str, optional): Content filtering level:
                                       - 'off': No filtering
                                       - 'moderate': Filter explicit content (default)
                                       - 'strict': Filter all adult content
            freshness (str, optional): Time-based filter for recent results:
                                      - 'pd': Past day (24 hours)
                                      - 'pw': Past week (7 days)
                                      - 'pm': Past month (31 days)
                                      - 'py': Past year (365 days)
                                      - None: All time (default)
            spellcheck (bool, optional): Enable spellcheck for the query. Default: False.
        
        Returns:
            str: JSON formatted string containing:
                - query: The original search query
                - web_results: List of web results with title, url, description
                - total_results: Total count of results
        """
        # Run async method in sync context
        return asyncio.run(
            self._brave_search_async(
                query, max_results, country, search_lang, safesearch, freshness, spellcheck
            )
        )
    
    def brave_news_search(
        self,
        query: str,
        max_results: int = 5,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        freshness: str = "pw",
        spellcheck: bool = False,
    ) -> str:
        """
        Dedicated news search optimized for recent articles (SYNC wrapper).
        
        Args:
            query (str): News search query.
            max_results (int, optional): Number of results (1-50, default: 5).
            country (str, optional): Country code. Uses fixed_country or defaults to 'US'.
            search_lang (str, optional): Language code. Uses fixed_language or defaults to 'en'.
            freshness (str, optional): Time filter - 'pd' (past day), 'pw' (past week, default), 
                                      'pm' (past month), 'py' (past year).
            spellcheck (bool, optional): Enable spellcheck. Default: False.
        
        Returns:
            str: JSON with news articles including title, URL, description, age, and source.
        """
        return asyncio.run(
            self._brave_news_search_async(
                query, max_results, country, search_lang, freshness, spellcheck
            )
        )
    
    def brave_video_search(
        self,
        query: str,
        max_results: int = 5,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        safesearch: str = "moderate",
        spellcheck: bool = False,
    ) -> str:
        """
        Dedicated video search for finding video content (SYNC wrapper).
        
        Args:
            query (str): Video search query.
            max_results (int, optional): Number of videos (1-50, default: 5).
            country (str, optional): Country code. Uses fixed_country or defaults to 'US'.
            search_lang (str, optional): Language code. Uses fixed_language or defaults to 'en'.
            safesearch (str, optional): Content filtering - 'off', 'moderate' (default), 'strict'.
            spellcheck (bool, optional): Enable spellcheck. Default: False.
        
        Returns:
            str: JSON with video results including title, URL, description, duration,
                 view count, creator name, and age.
        """
        return asyncio.run(
            self._brave_video_search_async(
                query, max_results, country, search_lang, safesearch, spellcheck
            )
        )
    
    def brave_image_search(
        self,
        query: str,
        max_results: int = 10,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        safesearch: str = "moderate",
        spellcheck: bool = False,
    ) -> str:
        """
        Dedicated image search with privacy protection (SYNC wrapper).
        
        Args:
            query (str): Image search query.
            max_results (int, optional): Number of images (1-100, default: 10).
            country (str, optional): Country code. Uses fixed_country or defaults to 'US'.
            search_lang (str, optional): Language code. Uses fixed_language or defaults to 'en'.
            safesearch (str, optional): Content filtering - 'off', 'moderate' (default), 'strict'.
            spellcheck (bool, optional): Enable spellcheck. Default: False.
        
        Returns:
            str: JSON with image results including title, URL, thumbnail, and source.
        """
        return asyncio.run(
            self._brave_image_search_async(
                query, max_results, country, search_lang, safesearch, spellcheck
            )
        )
    
    
    async def _brave_search_async(
        self,
        query: str,
        max_results: int = 5,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        safesearch: str = "moderate",
        freshness: Optional[str] = None,
        spellcheck: bool = False,
    ) -> str:
        """Async implementation of Brave web search."""
        if not query:
            return json.dumps({"error": "Query required"})
        
        params = self._get_params(max_results, country, search_lang)
        log_info(f"Searching Brave: {query}")
        
        try:
            # Build request using Pydantic model
            request = WebSearchRequest(
                q=query,
                count=min(params["max_results"], 20),  # API max is 20
                country=params["country"],
                search_lang=params["search_lang"],
                safesearch=safesearch,
                freshness=freshness,
                spellcheck=spellcheck,
            )
            
            # Execute async search
            response = await self.brave_client.web(request)
            
            # Extract results
            web_results = []
            if response.web and response.web.results:
                for r in response.web.results:
                    result = {
                        "title": r.title,
                        "url": str(r.url),
                        "description": r.description,
                    }
                    # Add optional metadata if available
                    if hasattr(r, "age") and r.age:
                        result["age"] = r.age
                    if hasattr(r, "page_age") and r.page_age:
                        result["page_age"] = str(r.page_age)
                    web_results.append(result)
            
            filtered = {
                "query": query,
                "web_results": web_results,
                "total_results": len(web_results),
            }
            
            return json.dumps(filtered, indent=2)
            
        except Exception as e:
            log_info(f"Search error: {str(e)}")
            return json.dumps({"error": f"Search failed: {str(e)}"})
    
    async def _brave_news_search_async(
        self,
        query: str,
        max_results: int = 5,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        freshness: str = "pw",
        spellcheck: bool = False,
    ) -> str:
        """Async implementation of news search."""
        if not query:
            return json.dumps({"error": "Query required"})
        
        params = self._get_params(max_results, country, search_lang)
        log_info(f"Searching Brave News: {query}")
        
        try:
            # Build news search request
            request = NewsSearchRequest(
                q=query,
                count=min(params["max_results"], 50),  # News API max is 50
                country=params["country"],
                search_lang=params["search_lang"],
                freshness=freshness,
                spellcheck=spellcheck,
            )
            
            # Execute async news search
            response = await self.brave_client.news(request)
            
            # Extract news results
            news_results = []
            if response.results:
                for r in response.results:
                    result = {
                        "title": r.title,
                        "url": str(r.url),
                        "description": r.description,
                    }
                    # Add news-specific metadata
                    if hasattr(r, "age") and r.age:
                        result["age"] = r.age
                    if hasattr(r, "page_age") and r.page_age:
                        result["page_age"] = str(r.page_age)
                    if hasattr(r, "meta_url") and r.meta_url:
                        result["source"] = r.meta_url.hostname if hasattr(r.meta_url, "hostname") else None
                    news_results.append(result)
            
            filtered = {
                "query": query,
                "news_results": news_results,
                "total_results": len(news_results),
            }
            
            return json.dumps(filtered, indent=2)
            
        except Exception as e:
            log_info(f"News search error: {str(e)}")
            return json.dumps({"error": f"News search failed: {str(e)}"})
    
    async def _brave_video_search_async(
        self,
        query: str,
        max_results: int = 5,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        safesearch: str = "moderate",
        spellcheck: bool = False,
    ) -> str:
        """Async implementation of video search."""
        if not query:
            return json.dumps({"error": "Query required"})
        
        params = self._get_params(max_results, country, search_lang)
        log_info(f"Searching Brave Videos: {query}")
        
        try:
            # Build video search request
            request = VideosSearchRequest(
                q=query,
                count=min(params["max_results"], 50),  # Videos API max is 50
                country=params["country"],
                search_lang=params["search_lang"],
                safesearch=safesearch,
                spellcheck=spellcheck,
            )
            
            # Execute async video search
            response = await self.brave_client.videos(request)
            
            # Extract video results
            video_results = []
            if response.results:
                for r in response.results:
                    result = {
                        "title": r.title if hasattr(r, "title") else "",
                        "url": str(r.url) if hasattr(r, "url") else "",
                        "description": r.description if hasattr(r, "description") else "",
                    }
                    # Add video-specific metadata
                    if hasattr(r, "age") and r.age:
                        result["age"] = r.age
                    if hasattr(r, "page_age") and r.page_age:
                        result["page_age"] = str(r.page_age)
                    if hasattr(r, "video") and r.video:
                        if hasattr(r.video, "duration"):
                            result["duration"] = r.video.duration
                        if hasattr(r.video, "views"):
                            result["views"] = r.video.views
                        if hasattr(r.video, "creator"):
                            result["creator"] = r.video.creator
                    video_results.append(result)
            
            filtered = {
                "query": query,
                "video_results": video_results,
                "total_results": len(video_results),
            }
            
            return json.dumps(filtered, indent=2)
            
        except Exception as e:
            log_info(f"Video search error: {str(e)}")
            return json.dumps({"error": f"Video search failed: {str(e)}"})
    
    async def _brave_image_search_async(
        self,
        query: str,
        max_results: int = 10,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        safesearch: str = "moderate",
        spellcheck: bool = False,
    ) -> str:
        """Async implementation of image search."""
        if not query:
            return json.dumps({"error": "Query required"})
        
        params = self._get_params(max_results, country, search_lang)
        log_info(f"Searching Brave Images: {query}")
        
        try:
            # Build image search request
            request = ImagesSearchRequest(
                q=query,
                count=min(params["max_results"], 100),  # Images API max is 100
                country=params["country"],
                search_lang=params["search_lang"],
                safesearch=safesearch,
                spellcheck=spellcheck,
            )
            
            # Execute async image search
            response = await self.brave_client.images(request)
            
            # Extract image results
            image_results = []
            if response.results:
                for r in response.results:
                    result = {
                        "title": r.title if hasattr(r, "title") else "",
                        "url": str(r.url) if hasattr(r, "url") else "",
                    }
                    # Add image-specific metadata
                    if hasattr(r, "thumbnail") and r.thumbnail:
                        result["thumbnail"] = str(r.thumbnail.src) if hasattr(r.thumbnail, "src") else None
                    if hasattr(r, "source"):
                        result["source"] = r.source
                    if hasattr(r, "properties") and r.properties:
                        if hasattr(r.properties, "url"):
                            result["image_url"] = str(r.properties.url)
                    image_results.append(result)
            
            filtered = {
                "query": query,
                "image_results": image_results,
                "total_results": len(image_results),
            }
            
            return json.dumps(filtered, indent=2)
            
        except Exception as e:
            log_info(f"Image search error: {str(e)}")
            return json.dumps({"error": f"Image search failed: {str(e)}"})


# Usage example for testing
if __name__ == "__main__":
    # Synchronous usage (works with agent.run())
    tools = BraveSearchTools(enable_web_search=True)
    result = tools.brave_search("Python programming", max_results=3)
    print("Sync result:", result)
    
    # Async usage (works with agent.arun())
    async def test_async():
        tools = BraveSearchTools(enable_web_search=True)
        result = await tools._brave_search_async("Python programming", max_results=3)
        print("Async result:", result)
    
    asyncio.run(test_async())
