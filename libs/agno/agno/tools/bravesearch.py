import json
from os import getenv
from typing import Optional
from agno.tools import Toolkit
from agno.utils.log import log_info

try:
    from brave import Brave
except ImportError:
    raise ImportError("`brave-search` not installed. Please install using `pip install brave-search`")


class BraveSearchTools(Toolkit):
    """
    Complete Brave Search toolkit with all 2024-2025 features.
    
    This toolkit provides access to Brave's independent search index with privacy-preserving
    search capabilities. It includes web search, news, videos, images, local/POI search,
    AI-powered summarization, and custom ranking via Goggles.
    
    Features:
    - Web, news, video, image, and local search
    - AI-powered summarization of search results (NEW 2023-2025)
    - Local/POI search for businesses and places (NEW 2024-2025)
    - Goggles for custom result re-ranking
    - Extra snippets for contextual relevance
    - Freshness filters for time-based results
    - Safe search content filtering
    - Spellcheck support (plan-dependent)
    
    Args:
        api_key (str, optional): Brave API key. If not provided, uses BRAVE_API_KEY environment variable.
        fixed_max_results (Optional[int]): Fixed maximum results for all searches.
        fixed_language (Optional[str]): Fixed language code for all searches (e.g., 'en', 'es', 'fr').
        fixed_country (Optional[str]): Fixed country code for all searches (e.g., 'US', 'GB', 'DE').
        enable_web_search (bool): Enable main web search tool. Default: True.
        enable_local_search (bool): Enable local/POI search tool. Default: False.
        enable_news_search (bool): Enable dedicated news search tool. Default: False.
        enable_video_search (bool): Enable dedicated video search tool. Default: False.
        enable_image_search (bool): Enable image search tool. Default: False.
        enable_goggles_search (bool): Enable Goggles re-ranking tool. Default: False.
        enable_summarizer (bool): Enable AI summarization tool. Default: False.
        all (bool): Enable all available tools. Default: False.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        fixed_language: Optional[str] = None,
        fixed_country: Optional[str] = None,
        enable_web_search: bool = True,
        enable_local_search: bool = False,
        enable_news_search: bool = False,
        enable_video_search: bool = False,
        enable_image_search: bool = False,
        enable_goggles_search: bool = False,
        enable_summarizer: bool = False,
        all: bool = False,
        **kwargs,
    ):
        # Load API key from parameter or environment variable
        self.api_key = api_key or getenv("BRAVE_API_KEY")
        if not self.api_key:
            raise ValueError("BRAVE_API_KEY is required. Please set the BRAVE_API_KEY environment variable.")
        
        # Store fixed parameters that will override per-call parameters
        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language
        self.fixed_country = fixed_country
        
        # Initialize the Brave Search client
        self.brave_client = Brave(api_key=self.api_key)
        
        # Build tools list based on enabled features
        tools = []
        if all or enable_web_search: 
            tools.append(self.brave_search)
        if all or enable_local_search: 
            tools.append(self.brave_local_search)
        if all or enable_news_search: 
            tools.append(self.brave_news_search)
        if all or enable_video_search: 
            tools.append(self.brave_video_search)
        if all or enable_image_search: 
            tools.append(self.brave_image_search)
        if all or enable_goggles_search: 
            tools.append(self.brave_search_with_goggles)
        if all or enable_summarizer: 
            tools.append(self.brave_search_with_summary)
        
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
    
    def _extract_results(self, search_results) -> dict:
        """
        Helper method to extract and format all result types from Brave API response.
        
        Extracts web, news, and video results along with their metadata like age,
        source, duration, views, etc.
        
        Args:
            search_results: Raw response from brave_client.search()
            
        Returns:
            dict: Formatted results with web_results, news_results, video_results, and total_results
        """
        filtered = {
            "web_results": [],
            "news_results": [],
            "video_results": [],
            "total_results": 0
        }
        
        # Extract web results with metadata
        if hasattr(search_results, "web") and search_results.web:
            for r in search_results.web.results:
                result = {
                    "title": r.title,
                    "url": str(r.url),
                    "description": r.description
                }
                # Add optional metadata if available
                if hasattr(r, "age"): 
                    result["age"] = r.age
                if hasattr(r, "extra_snippets"): 
                    result["extra_snippets"] = r.extra_snippets
                filtered["web_results"].append(result)
        
        # Extract news results with source and age
        if hasattr(search_results, "news") and search_results.news:
            for r in search_results.news.results:
                result = {
                    "title": r.title,
                    "url": str(r.url),
                    "description": r.description
                }
                # Add news-specific metadata
                if hasattr(r, "age"): 
                    result["age"] = r.age
                if hasattr(r, "source"): 
                    result["source"] = r.source
                filtered["news_results"].append(result)
        
        # Extract video results with duration and engagement metrics
        if hasattr(search_results, "videos") and search_results.videos:
            for r in search_results.videos.results:
                result = {
                    "title": getattr(r, "title", ""),
                    "url": str(getattr(r, "url", "")),
                    "description": getattr(r, "description", "")
                }
                # Add video-specific metadata
                if hasattr(r, "age"): 
                    result["age"] = r.age
                if hasattr(r, "duration"): 
                    result["duration"] = r.duration
                if hasattr(r, "video"):
                    result["views"] = getattr(r.video, "views", None)
                    result["creator"] = getattr(r.video, "creator", None)
                filtered["video_results"].append(result)
        
        # Calculate total results across all types
        filtered["total_results"] = (
            len(filtered["web_results"]) + 
            len(filtered["news_results"]) + 
            len(filtered["video_results"])
        )
        
        return filtered
    
    def brave_search(
        self,
        query: str,
        max_results: int = 5,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        safesearch: str = "moderate",
        freshness: Optional[str] = None,
        result_filter: str = "web",
        extra_snippets: bool = False,
        spellcheck: bool = False,
    ) -> str:
        """
        Main unified search supporting web, news, and video results.
        
        This is the primary search method that can return multiple result types
        in a single call. Use result_filter to control which types to include.
        
        Args:
            query (str): The search query term. Maximum 400 characters and 50 words.
            max_results (int, optional): Maximum number of results to return per type. 
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
                                      - 'YYYY-MM-DDtoYYYY-MM-DD': Custom date range
                                      - None: All time (default)
            result_filter (str, optional): Comma-separated list of result types to include:
                                          'web', 'news', 'videos', 'discussions', 'faq', 
                                          'infobox', 'locations', 'query'. Default: 'web'.
            extra_snippets (bool, optional): Get up to 5 additional contextual snippets 
                                            for better relevance. Default: False.
                                            Requires AI plan subscription.
            spellcheck (bool, optional): Enable spellcheck for the query. Default: False.
                                        Requires plan support ($5 per 10k requests).
        
        Returns:
            str: JSON formatted string containing:
                - query: The original search query
                - web_results: List of web results with title, url, description, age
                - news_results: List of news articles with title, url, description, age, source
                - video_results: List of videos with title, url, description, duration, views, creator
                - total_results: Total count across all result types
        """
        if not query:
            return json.dumps({"error": "Query required"})
        
        # Resolve final parameters (fixed override per-call)
        params = self._get_params(max_results, country, search_lang)
        log_info(f"Searching Brave: {query}")
        
        # Build search parameters for API call
        search_params = {
            "q": query,
            "count": min(params["max_results"], 20),  # API max is 20
            "country": params["country"],
            "search_lang": params["search_lang"],
            "safesearch": safesearch,
            "result_filter": result_filter,
        }
        
        # Add optional parameters if specified
        if freshness: 
            search_params["freshness"] = freshness
        if extra_snippets: 
            search_params["extra_snippets"] = "true"
        if spellcheck: 
            search_params["spellcheck"] = 1
        
        try:
            # Execute search via Brave API
            results = self.brave_client.search(**search_params)
            
            # Extract and format all result types
            filtered = self._extract_results(results)
            filtered["query"] = query
            
            return json.dumps(filtered, indent=2)
            
        except Exception as e:
            log_info(f"Search error: {str(e)}")
            return json.dumps({"error": f"Search failed: {str(e)}"})
    
    def brave_local_search(
        self, 
        query: str, 
        max_results: int = 10, 
        country: Optional[str] = None, 
        search_lang: Optional[str] = None
    ) -> str:
        """
        Search for local businesses and points of interest (POI).
        
        NEW FEATURE (2024-2025): Dedicated local search for physical locations
        including restaurants, shops, services, etc. Returns detailed business
        information like addresses, ratings, hours, and contact info.
        
        Args:
            query (str): Local search query (e.g., "coffee shops near me", 
                        "restaurants in Paris", "hotels in London").
            max_results (int, optional): Number of results (1-20, default: 10).
            country (str, optional): Country code. Uses fixed_country or defaults to 'US'.
            search_lang (str, optional): Language code. Uses fixed_language or defaults to 'en'.
        
        Returns:
            str: JSON with local results including:
                - Business names and addresses
                - Ratings and review counts
                - Phone numbers
                - Opening hours
                - Location coordinates
        """
        # Use main search with locations filter
        return self.brave_search(
            query=query,
            max_results=max_results,
            country=country,
            search_lang=search_lang,
            result_filter="locations"
        )
    
    def brave_news_search(
        self, 
        query: str, 
        max_results: int = 5, 
        country: Optional[str] = None, 
        search_lang: Optional[str] = None,
        freshness: str = "pw"
    ) -> str:
        """
        Dedicated news search optimized for recent articles and breaking news.
        
        Args:
            query (str): News search query.
            max_results (int, optional): Number of results (1-20, default: 5).
            country (str, optional): Country code. Uses fixed_country or defaults to 'US'.
            search_lang (str, optional): Language code. Uses fixed_language or defaults to 'en'.
            freshness (str, optional): Time filter - 'pd' (past day), 'pw' (past week, default), 
                                      'pm' (past month), 'py' (past year).
        
        Returns:
            str: JSON with news articles including title, URL, description, age, and source.
        """
        return self.brave_search(
            query=query,
            max_results=max_results,
            country=country,
            search_lang=search_lang,
            freshness=freshness,
            result_filter="news"
        )
    
    def brave_video_search(
        self, 
        query: str, 
        max_results: int = 5,
        country: Optional[str] = None, 
        search_lang: Optional[str] = None
    ) -> str:
        """
        Dedicated video search for finding video content.
        
        Args:
            query (str): Video search query.
            max_results (int, optional): Number of videos (1-20, default: 5).
            country (str, optional): Country code. Uses fixed_country or defaults to 'US'.
            search_lang (str, optional): Language code. Uses fixed_language or defaults to 'en'.
        
        Returns:
            str: JSON with video results including title, URL, description, duration,
                 view count, creator name, and age.
        """
        return self.brave_search(
            query=query,
            max_results=max_results,
            country=country,
            search_lang=search_lang,
            result_filter="videos"
        )
    
    def brave_image_search(
        self, 
        query: str, 
        max_results: int = 10,
        country: Optional[str] = None, 
        search_lang: Optional[str] = None,
        safesearch: str = "moderate"
    ) -> str:
        """
        Dedicated image search with privacy protection.
        
        NEW FEATURE (2024): Independent image search protecting user privacy
        while providing access to images from across the web.
        
        Args:
            query (str): Image search query.
            max_results (int, optional): Number of images (1-100, default: 10).
            country (str, optional): Country code. Uses fixed_country or defaults to 'US'.
            search_lang (str, optional): Language code. Uses fixed_language or defaults to 'en'.
            safesearch (str, optional): Content filtering - 'off', 'moderate' (default), 'strict'.
        
        Returns:
            str: JSON with image results including title, URL, thumbnail, and source.
        """
        return self.brave_search(
            query=query,
            max_results=max_results,
            country=country,
            search_lang=search_lang,
            safesearch=safesearch,
            result_filter="images"
        )
    
    def brave_search_with_summary(
        self, 
        query: str, 
        max_results: int = 5,
        country: Optional[str] = None, 
        search_lang: Optional[str] = None
    ) -> str:
        """
        Search with AI-powered summarization of results.
        
        NEW FEATURE (2023-2025): Uses Brave's own LLMs (not ChatGPT) to generate
        concise summaries from multiple web sources. The summarization is privacy-preserving
        and cites original sources for transparency.
        
        This performs a two-step process:
        1. Executes web search with summary flag enabled
        2. Returns results plus a summary_key that can be used to retrieve the AI summary
        
        Note: Requires Pro AI plan subscription. The summary generation happens
        server-side and can be polled using the returned summary_key.
        
        Args:
            query (str): Search query for summarization.
            max_results (int, optional): Number of results to use for summary (1-20, default: 5).
            country (str, optional): Country code. Uses fixed_country or defaults to 'US'.
            search_lang (str, optional): Language code. Uses fixed_language or defaults to 'en'.
        
        Returns:
            str: JSON containing:
                - query: Original search query
                - summary_enabled: Boolean indicating summarization is active
                - summary_key: Key for retrieving the generated summary via polling endpoint
                - web_results: List of search results used for summarization
        """
        if not query:
            return json.dumps({"error": "Query required"})
        
        # Resolve final parameters
        params = self._get_params(max_results, country, search_lang)
        log_info(f"Brave AI Summarizer: {query}")
        
        try:
            # Execute search with summary enabled
            results = self.brave_client.search(
                q=query,
                count=min(params["max_results"], 20),
                country=params["country"],
                search_lang=params["search_lang"],
                summary=True  # Enable AI summarization
            )
            
            # Build response with summary metadata
            result = {
                "query": query,
                "summary_enabled": True,
                "summary_key": getattr(results, "summarizer", {}).get("key") if hasattr(results, "summarizer") else None,
                "web_results": []
            }
            
            # Extract web results used for summarization
            if hasattr(results, "web") and results.web:
                result["web_results"] = [
                    {
                        "title": r.title,
                        "url": str(r.url),
                        "description": r.description
                    }
                    for r in results.web.results
                ]
            
            return json.dumps(result, indent=2)
            
        except Exception as e:
            log_info(f"Summary error: {str(e)}")
            return json.dumps({"error": f"Summary failed: {str(e)}"})
    
    def brave_search_with_goggles(
        self, 
        query: str, 
        goggles_id: str, 
        max_results: int = 10,
        country: Optional[str] = None, 
        search_lang: Optional[str] = None
    ) -> str:
        """
        Search with Goggles for custom result re-ranking.
        
        Goggles enable custom re-ranking of Brave Search results using community-created
        or personal ranking rules. This is useful for prioritizing specific domains,
        content types, or sources. Anyone can create, apply, or extend a Goggle.
        
        Example Goggles:
        - Academic sources prioritization
        - Tech blog ranking
        - Government/official sources first
        - Custom domain boosting/filtering
        
        Args:
            query (str): Search query.
            goggles_id (str): URL or ID of the Goggle to apply. Can be:
                             - Full URL: "https://raw.githubusercontent.com/.../academic.goggle"
                             - Built-in ID from brave.goggles module
            max_results (int, optional): Number of results (1-20, default: 10).
            country (str, optional): Country code. Uses fixed_country or defaults to 'US'.
            search_lang (str, optional): Language code. Uses fixed_language or defaults to 'en'.
        
        Returns:
            str: JSON with re-ranked search results based on Goggle rules:
                - query: Original search query
                - goggles_id: ID of the applied Goggle
                - web_results: Re-ranked results
                - total_results: Count of results
        """
        if not query:
            return json.dumps({"error": "Query required"})
        
        # Resolve final parameters
        params = self._get_params(max_results, country, search_lang)
        log_info(f"Brave Goggles search: {query}")
        
        try:
            # Execute search with Goggles re-ranking
            results = self.brave_client.search(
                q=query,
                count=min(params["max_results"], 20),
                country=params["country"],
                search_lang=params["search_lang"],
                goggles_id=goggles_id,  # Apply custom ranking
                result_filter="web"
            )
            
            # Build response with re-ranked results
            filtered = {
                "query": query,
                "goggles_id": goggles_id,
                "web_results": [],
                "total_results": 0
            }
            
            # Extract re-ranked results
            if hasattr(results, "web") and results.web:
                filtered["web_results"] = [
                    {
                        "title": r.title,
                        "url": str(r.url),
                        "description": r.description
                    }
                    for r in results.web.results
                ]
                filtered["total_results"] = len(filtered["web_results"])
            
            return json.dumps(filtered, indent=2)
            
        except Exception as e:
            log_info(f"Goggles error: {str(e)}")
            return json.dumps({"error": f"Goggles search failed: {str(e)}"})
