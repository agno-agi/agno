from os import getenv
from typing import List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from apify_client import ApifyClient
except ImportError:
    raise ImportError("`apify_client` not installed. Please install using `pip install apify-client`")


class ApifyTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        max_results: int = 4,
        use_rag_web_search: bool = True,
        use_website_content_crawler: bool = False,
        use_web_scraper: bool = False,
        use_instagram_scraper: bool = True,
        use_google_places_crawler: bool = True
    ):
        """
        Initialize ApifyTools with various web scraping and data extraction capabilities.

        :param api_key: Apify API key (optional, can be set via APIFY_TOKEN environment variable)
        :param max_results: Maximum number of results for web searches
        :param use_rag_web_search: Enable RAG web search tool
        :param use_website_content_crawler: Enable website content crawler tool
        :param use_web_scraper: Enable general web scraper tool
        :param use_instagram_scraper: Enable Instagram scraper tool
        :param use_google_places_crawler: Enable Google Places crawler tool
        """
        super().__init__(name="apify_tools")
        
        self.api_key = api_key or getenv("APIFY_TOKEN")
        self.max_results = max_results
        
        if not self.api_key:
            logger.error("No Apify API key provided")
        
        # Register tools based on user preferences
        if use_rag_web_search:
            self.register(self.rag_web_search)
        if use_website_content_crawler:
            self.register(self.website_content_crawler)
        if use_web_scraper:
            self.register(self.web_scraper)
        if use_instagram_scraper:
            self.register(self.instagram_scraper)
        if use_google_places_crawler:
            self.register(self.google_places_crawler)

    def rag_web_search(self, query: str, timeout: Optional[int] = 45) -> str:
        """
        Search the web for information using the RAG Web Browser actor.
        
        :param query: Search query or topic to research. Enter Google Search keywords or a URL of a specific web page.
                     The keywords might include the advanced search operators. Examples:
                     - san francisco weather
                     - https://www.cnn.com
                     - function calling site:openai.com
        :param timeout: Maximum time (in seconds) for searching
        :return: Formatted string containing search results
        """
        if self.api_key is None:
            return "No API key provided"
            
        client = ApifyClient(self.api_key)
        log_debug(f"Searching for: {query}")
        
        run_input = {
            "query": query,
            "maxResults": self.max_results,
            "requestTimeoutSecs": timeout
        }
        
        run = client.actor("apify/rag-web-browser").call(run_input=run_input)
        
        results_text = f"Search Results for: {query}\n\n"
        
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            metadata = item.get('metadata', {})
            crawl_info = item.get('crawl', {})
            content = item.get('markdown', item.get('text', 'No content extracted'))
            
            results_text += f"URL: {metadata.get('url', 'Unknown source')}\n"
            results_text += f"Title: {metadata.get('title', 'No title')}\n"
            results_text += f"Description: {metadata.get('description', 'No description')}\n"
            results_text += f"Content:\n{content}\n"
            results_text += f"Language: {metadata.get('languageCode', 'unknown')}\n"
            results_text += f"Status Code: {crawl_info.get('httpStatusCode', 'N/A')}\n"
            results_text += f"Loaded At: {crawl_info.get('loadedAt', 'N/A')}\n"
            results_text += "-" * 30 + "\n\n"
        
        return results_text

    def website_content_crawler(self, urls: List[str], timeout: Optional[int] = 60) -> str:
        """
        Crawls websites using Apify's website-content-crawler actor.

        :param urls: List of URLs to crawl
        :param timeout: Maximum time (in seconds) for crawling
        :return: Extracted text content from the websites
        """
        if self.api_key is None:
            return "No API key provided"

        if not urls:
            return "No URLs provided"

        client = ApifyClient(self.api_key)
        log_debug(f"Crawling URLs: {urls}")

        formatted_urls = [{"url": url} for url in urls]
        run_input = {"startUrls": formatted_urls}

        run = client.actor("apify/website-content-crawler").call(run_input=run_input, timeout_secs=timeout)
        results = ""

        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            results += f"Results for URL: {item.get('url')}\n"
            results += f"{item.get('text')}\n\n"

        return results

    def web_scraper(self, urls: List[str], timeout: Optional[int] = 60) -> str:
        """
        Scrapes websites using Apify's web-scraper actor.

        :param urls: List of URLs to scrape
        :param timeout: Maximum time (in seconds) for scraping
        :return: Extracted structured data from the websites
        """
        if self.api_key is None:
            return "No API key provided"

        if not urls:
            return "No URLs provided"

        client = ApifyClient(self.api_key)
        log_debug(f"Scraping URLs: {urls}")

        formatted_urls = [{"url": url} for url in urls]
        
        page_function_string = """
            async function pageFunction(context) {
                const $ = context.jQuery;
                const pageTitle = $('title').first().text();
                const h1 = $('h1').first().text();
                const first_h2 = $('h2').first().text();
                const random_text_from_the_page = $('p').first().text();

                context.log.info(`URL: ${context.request.url}, TITLE: ${pageTitle}`);

                return {
                    url: context.request.url,
                    pageTitle,
                    h1,
                    first_h2,
                    random_text_from_the_page
                };
            }
        """

        run_input = {
            "pageFunction": page_function_string,
            "startUrls": formatted_urls,
        }

        run = client.actor("apify/web-scraper").call(run_input=run_input, timeout_secs=timeout)
        results = ""

        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            results += f"Results for URL: {item.get('url')}\n"
            results += f"Title: {item.get('pageTitle')}\n"
            results += f"H1: {item.get('h1')}\n"
            results += f"First H2: {item.get('first_h2')}\n"
            results += f"Sample text: {item.get('random_text_from_the_page')}\n\n"

        return results

    def instagram_scraper(
        self, 
        search: Optional[str] = None,
        search_type: Optional[str] = "user",
        search_limit: Optional[int] = 10,
        timeout: Optional[int] = 180
    ) -> str:
        """
        Scrape Instagram profiles, hashtags, or places.
        
        :param search: Search query for profiles, hashtags or places
        :param search_type: Type of search - "user", "hashtag", or "place"
        :param search_limit: Number of search results to return
        :param timeout: Maximum time (in seconds) for scraping
        :return: Extracted Instagram data
        """
        if self.api_key is None:
            return "No API key provided"

        client = ApifyClient(self.api_key)
        log_debug(f"Searching Instagram for: {search} (type: {search_type})")

        run_input = {
            "search": search,
            "searchType": search_type,
            "searchLimit": search_limit,
        }

        run = client.actor("apify/instagram-scraper").call(run_input=run_input, timeout_secs=timeout)
        results = ""

        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            results += f"Result type: {search_type}\n"
            if search_type == "user":
                results += f"Username: {item.get('username')}\n"
                results += f"Full name: {item.get('fullName')}\n"
                results += f"Followers: {item.get('followersCount')}\n"
            elif search_type == "hashtag":
                results += f"Hashtag: {item.get('name')}\n"
                results += f"Post count: {item.get('postsCount')}\n"
            elif search_type == "place":
                results += f"Place: {item.get('name')}\n"
                results += f"Location: {item.get('location')}\n"
            results += "-" * 30 + "\n\n"

        return results

    def google_places_crawler(
        self,
        location_query: str,
        search_terms: Optional[List[str]] = None,
        max_crawled_places: Optional[int] = 30,
        timeout: Optional[int] = 45
    ) -> str:
        """
        Crawl Google Places for business information.
        
        :param location_query: Location to search in (City + Country format works best)
        :param search_terms: List of search terms (e.g. ["restaurant", "cafe"])
        :param max_crawled_places: Maximum number of places to extract per search
        :param timeout: Maximum time (in seconds) for crawling
        :return: Extracted business information
        """
        if self.api_key is None:
            return "No API key provided"

        client = ApifyClient(self.api_key)
        log_debug(f"Crawling Google Places in: {location_query}")

        run_input = {
            "locationQuery": location_query,
            "maxCrawledPlacesPerSearch": max_crawled_places,
            "searchStringsArray": search_terms or ["restaurant"],  # Default to restaurants if no search terms provided
        }

        run = client.actor("compass/crawler-google-places").call(run_input=run_input, timeout_secs=timeout)
        results = ""

        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            results += f"Business: {item.get('name')}\n"
            results += f"Address: {item.get('address')}\n"
            results += f"Rating: {item.get('rating')}\n"
            results += f"Reviews: {item.get('reviewsCount')}\n"
            results += f"Phone: {item.get('phone')}\n"
            results += f"Website: {item.get('website')}\n"
            results += "-" * 30 + "\n\n"

        return results