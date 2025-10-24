import json
from os import getenv
from typing import Any, List, Optional
from time import sleep

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class ScrapeGraphTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_smartscraper: bool = True,
        enable_markdownify: bool = False,
        enable_crawl: bool = False,
        enable_searchscraper: bool = False,
        enable_agentic_crawler: bool = False,
        enable_scrape: bool = False,
        render_heavy_js: bool = False,
        all: bool = False,
        base_url: str = "https://api.scrapegraphai.com/v1",
        timeout: int = 300,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("SGAI_API_KEY")
        if not self.api_key:
            raise ValueError("API key is required. Set SGAI_API_KEY environment variable or pass api_key parameter.")
        
        self.base_url = base_url
        self.timeout = timeout
        self.render_heavy_js = render_heavy_js
        self.headers = {
            "SGAI-APIKEY": self.api_key,
            "Content-Type": "application/json"
        }

        # Start with smartscraper by default
        # Only enable markdownify if smartscraper is False
        if not enable_smartscraper and not all:
            enable_markdownify = True

        tools: List[Any] = []
        if enable_smartscraper or all:
            tools.append(self.smartscraper)
        if enable_markdownify or all:
            tools.append(self.markdownify)
        if enable_crawl or all:
            tools.append(self.crawl)
        if enable_searchscraper or all:
            tools.append(self.searchscraper)
        if enable_agentic_crawler or all:
            tools.append(self.agentic_crawler)
        if enable_scrape or all:
            tools.append(self.scrape)

        super().__init__(name="scrapegraph_tools", tools=tools, **kwargs)

    def _make_request(self, method: str, endpoint: str, data: Optional[dict] = None) -> dict:
        """Make HTTP request to ScrapeGraphAI API"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            with httpx.Client(timeout=self.timeout) as client:
                if method == "GET":
                    response = client.get(url, headers=self.headers)
                elif method == "POST":
                    response = client.post(url, headers=self.headers, json=data)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            log_error(error_msg)
            raise Exception(error_msg)
        except Exception as e:
            log_error(f"Request failed: {str(e)}")
            raise

    def _wait_for_completion(self, endpoint: str, request_id: str, max_retries: int = 60, retry_delay: int = 2) -> dict:
        """Poll endpoint until request is completed"""
        for _ in range(max_retries):
            response = self._make_request("GET", f"{endpoint}/{request_id}")
            status = response.get("status", "")
            
            if status == "completed":
                return response
            elif status == "failed":
                raise Exception(f"Request failed: {response.get('error', 'Unknown error')}")
            elif status in ["queued", "processing"]:
                sleep(retry_delay)
            else:
                raise Exception(f"Unknown status: {status}")
        
        raise Exception("Request timed out")

    def smartscraper(self, url: str, prompt: str) -> str:
        """Extract structured data from a webpage using LLM.
        Args:
            url (str): The URL to scrape
            prompt (str): Natural language prompt describing what to extract
        Returns:
            The structured data extracted from the webpage
        """
        try:
            log_debug(f"ScrapeGraph smartscraper request for URL: {url}")
            
            payload = {
                "website_url": url,
                "user_prompt": prompt,
                "render_heavy_js": self.render_heavy_js
            }
            
            response = self._make_request("POST", "/smartscraper", payload)
            request_id = response.get("request_id")
            
            if not request_id:
                return json.dumps(response.get("result"))
            
            # Wait for completion
            completed_response = self._wait_for_completion("/smartscraper", request_id)
            return json.dumps(completed_response.get("result"))
            
        except Exception as e:
            error_msg = f"Smartscraper failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def markdownify(self, url: str) -> str:
        """Convert a webpage to markdown format.
        Args:
            url (str): The URL to convert
        Returns:
            The markdown version of the webpage
        """
        try:
            log_debug(f"ScrapeGraph markdownify request for URL: {url}")
            
            payload = {
                "website_url": url
            }
            
            response = self._make_request("POST", "/markdownify", payload)
            request_id = response.get("request_id")
            
            if not request_id:
                return response.get("result", "")
            
            # Wait for completion
            completed_response = self._wait_for_completion("/markdownify", request_id)
            return completed_response.get("result", "")
            
        except Exception as e:
            error_msg = f"Markdownify failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def crawl(
        self,
        url: str,
        prompt: str,
        schema: dict,
        cache_website: bool = True,
        depth: int = 2,
        max_pages: int = 2,
        same_domain_only: bool = True,
        batch_size: int = 1,
    ) -> str:
        """Crawl a website and extract structured data
        Args:
            url (str): The URL to crawl
            prompt (str): Natural language prompt describing what to extract
            schema (dict): JSON schema for extraction
            cache_website (bool): Whether to cache the website
            depth (int): Crawl depth
            max_pages (int): Max number of pages to crawl
            same_domain_only (bool): Restrict to same domain
            batch_size (int): Batch size for crawling
        Returns:
            The structured data extracted from the website
        """
        try:
            log_debug(f"ScrapeGraph crawl request for URL: {url}")
            
            payload = {
                "url": url,
                "prompt": prompt,
                "schema": schema,
                "depth": depth,
                "max_pages": max_pages,
                "extraction_mode": True,
                "render_heavy_js": self.render_heavy_js,
                "rules": {
                    "same_domain": same_domain_only
                }
            }
            
            response = self._make_request("POST", "/crawl", payload)
            task_id = response.get("task_id")
            
            if not task_id:
                return json.dumps(response, indent=2)
            
            # Wait for completion (crawl may take longer)
            completed_response = self._wait_for_completion("/crawl", task_id, max_retries=120, retry_delay=3)
            return json.dumps(completed_response, indent=2)
            
        except Exception as e:
            error_msg = f"Crawl failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def agentic_crawler(
        self,
        url: str,
        steps: List[str],
        use_session: bool = True,
        user_prompt: Optional[str] = None,
        output_schema: Optional[dict] = None,
        ai_extraction: bool = False,
    ) -> str:
        """Perform agentic crawling with automated browser actions and optional AI extraction.

        This tool can:
        1. Navigate to a website
        2. Perform a series of automated actions (like filling forms, clicking buttons)
        3. Extract the resulting HTML content as markdown
        4. Optionally use AI to extract structured data

        Args:
            url (str): The URL to scrape
            steps (List[str]): List of steps to perform on the webpage (e.g., ["Type email in input box", "click login"])
            use_session (bool): Whether to use session for the scraping (default: True)
            user_prompt (Optional[str]): Prompt for AI extraction (only used when ai_extraction=True)
            output_schema (Optional[dict]): Schema for structured data extraction (only used when ai_extraction=True)
            ai_extraction (bool): Whether to use AI for data extraction from the scraped content (default: False)

        Returns:
            JSON string containing the scraping results, including request_id, status, and extracted data
        """
        try:
            log_debug(f"ScrapeGraph agentic_crawler request for URL: {url}")

            # Prepare payload for the API call
            payload = {
                "url": url,
                "steps": steps,
                "use_session": use_session,
                "ai_extraction": ai_extraction
            }

            # Add optional parameters only if they are provided
            if user_prompt:
                payload["user_prompt"] = user_prompt
            if output_schema:
                payload["output_schema"] = output_schema

            # Call the agentic scraper API
            response = self._make_request("POST", "/agentic-scrapper", payload)
            return json.dumps(response, indent=2)

        except Exception as e:
            error_msg = f"Agentic crawler failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def searchscraper(self, user_prompt: str) -> str:
        """Search the web and extract information from the web.
        Args:
            user_prompt (str): Search query
        Returns:
            JSON of the search results
        """
        try:
            log_debug(f"ScrapeGraph searchscraper request with prompt: {user_prompt}")
            
            payload = {
                "user_prompt": user_prompt,
                "extraction_mode": True
            }
            
            response = self._make_request("POST", "/searchscraper", payload)
            request_id = response.get("request_id")
            
            if not request_id:
                return json.dumps(response.get("result"))
            
            # Wait for completion
            completed_response = self._wait_for_completion("/searchscraper", request_id)
            return json.dumps(completed_response.get("result"))
            
        except Exception as e:
            error_msg = f"Searchscraper failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def scrape(
        self,
        website_url: str,
        headers: Optional[dict] = None,
    ) -> str:
        """Get raw HTML content from a website using the ScrapeGraphAI scrape API.

        Args:
            website_url (str): The URL of the website to scrape
            headers (Optional[dict]): Optional headers to send with the request

        Returns:
            JSON string containing the HTML content and metadata
        """
        try:
            log_debug(f"ScrapeGraph scrape request for URL: {website_url}")
            
            payload = {
                "website_url": website_url,
                "render_heavy_js": self.render_heavy_js
            }
            
            if headers:
                payload["headers"] = headers
            
            response = self._make_request("POST", "/scrape", payload)
            return json.dumps(response, indent=2)
            
        except Exception as e:
            error_msg = f"Scrape failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"
