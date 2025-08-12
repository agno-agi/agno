import json
from os import getenv
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info

try:
    from oxylabs import RealtimeClient
    from oxylabs.sources.response import Response
    from oxylabs.utils.types import render
except ImportError:
    raise ImportError("Oxylabs SDK not found. Please install it with: pip install oxylabs")


class OxylabsTools(Toolkit):
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs,
    ):
        self.username = username or getenv("OXYLABS_USERNAME")
        self.password = password or getenv("OXYLABS_PASSWORD")

        if not self.username or not self.password:
            raise ValueError(
                "No Oxylabs credentials provided. Please set the OXYLABS_USERNAME and OXYLABS_PASSWORD environment variables or pass them to the OxylabsTools constructor."
            )

        try:
            log_debug(f"Initializing Oxylabs client with username: {self.username[:5]}...")
            self.client = RealtimeClient(self.username, self.password)
            log_debug("Oxylabs client initialized successfully")
        except Exception as e:
            log_debug(f"Failed to initialize Oxylabs client: {e}")
            raise

        tools: List[Callable[..., str]] = [
            self.search_google,
            self.get_amazon_product,
            self.search_amazon_products,
            self.scrape_website,
        ]

        super().__init__(name="oxylabs_web_scraping", tools=tools, **kwargs)

    def search_google(self, query: str, domain_code: str = "com") -> str:
        """Search Google for a query.

        Args:
            query: Search query
            domain_code: Google domain to search (e.g., "com", "co.uk", "de", default: "com")

        Returns:
            JSON of search results
        """
        try:
            if not query or not isinstance(query, str) or len(query.strip()) == 0:
                return self._error_response("search_google", "Query cannot be empty", {"query": query})

            if not isinstance(domain_code, str) or len(domain_code) > 10:
                return self._error_response("search_google", "Domain must be a valid string (e.g., 'com', 'co.uk')")

            query = query.strip()
            log_debug(f"Google search: '{query}' on google.{domain_code}")

            response: Response = self.client.google.scrape_search(query=query, domain=domain_code, parse=True)

            # Extract search results
            search_results = []

            if response.results and len(response.results) > 0:
                result = response.results[0]

                # Try parsed content first
                if hasattr(result, "content_parsed") and result.content_parsed:
                    content = result.content_parsed
                    if hasattr(content, "results") and content.results:
                        raw_results = content.results.raw if hasattr(content.results, "raw") else {}
                        organic_results = raw_results.get("organic", [])

                        for item in organic_results:
                            search_results.append(
                                {
                                    "title": item.get("title", "").strip(),
                                    "url": item.get("url", "").strip(),
                                    "description": item.get("desc", "").strip(),
                                    "position": item.get("pos", 0),
                                }
                            )

                if not search_results and hasattr(result, "content"):
                    raw_content = result.content
                    if isinstance(raw_content, dict) and "results" in raw_content:
                        organic_results = raw_content["results"].get("organic", [])
                        for item in organic_results:
                            search_results.append(
                                {
                                    "title": item.get("title", "").strip(),
                                    "url": item.get("url", "").strip(),
                                    "description": item.get("desc", "").strip(),
                                    "position": item.get("pos", 0),
                                }
                            )

            response_data = {
                "tool": "search_google",
                "query": query,
                "results": search_results,
            }

            log_info(f"Google search completed. Found {len(search_results)} results")
            return json.dumps(response_data, indent=2)

        except Exception as e:
            error_msg = f"Google search failed: {str(e)}"
            log_error(error_msg)
            return self._error_response("search_google", error_msg, {"query": query})

    def get_amazon_product(self, asin: str, domain_code: str = "com") -> str:
        """Get detailed information about an Amazon product by ASIN.

        Args:
            asin: Amazon Standard Identification Number (10 alphanumeric characters, e.g., "B07FZ8S74R")
            domain_code: Amazon domain (e.g., "com", "co.uk", "de", default: "com")

        Returns:
            JSON of product details
        """
        try:
            if not asin or not isinstance(asin, str):
                return self._error_response("get_amazon_product", "ASIN is required and must be a string")

            asin = asin.strip().upper()
            if len(asin) != 10 or not asin.isalnum():
                return self._error_response(
                    "get_amazon_product",
                    f"Invalid ASIN format: {asin}. Must be 10 alphanumeric characters (e.g., 'B07FZ8S74R')",
                )

            if not isinstance(domain_code, str) or len(domain_code) > 10:
                return self._error_response(
                    "get_amazon_product", "Domain must be a valid string (e.g., 'com', 'co.uk')"
                )

            log_debug(f"Amazon product lookup: ASIN {asin} on amazon.{domain_code}")

            response: Response = self.client.amazon.scrape_product(query=asin, domain=domain_code, parse=True)

            product_info = {"found": False, "asin": asin, "domain": f"amazon.{domain_code}"}

            if response.results and len(response.results) > 0:
                result = response.results[0]

                if hasattr(result, "content") and result.content:
                    content = result.content
                    if isinstance(content, dict):
                        product_info.update(
                            {
                                "found": True,
                                "title": content.get("title", "").strip(),
                                "price": content.get("price", 0),
                                "currency": content.get("currency", ""),
                                "rating": content.get("rating", 0),
                                "reviews_count": content.get("reviews_count", 0),
                                "url": content.get("url", ""),
                                "description": content.get("description", "").strip(),
                                "stock_status": content.get("stock", "").strip(),
                                "brand": content.get("brand", "").strip(),
                                "images": content.get("images", [])[:3],
                                "bullet_points": content.get("bullet_points", [])[:5]
                                if content.get("bullet_points")
                                else [],
                            }
                        )

                elif hasattr(result, "content_parsed") and result.content_parsed:
                    content = result.content_parsed
                    product_info.update(
                        {
                            "found": True,
                            "title": getattr(content, "title", "").strip(),
                            "price": getattr(content, "price", 0),
                            "currency": getattr(content, "currency", ""),
                            "rating": getattr(content, "rating", 0),
                            "reviews_count": getattr(content, "reviews_count", 0),
                            "url": getattr(content, "url", ""),
                            "description": getattr(content, "description", "").strip(),
                            "stock_status": getattr(content, "stock", "").strip(),
                            "brand": getattr(content, "brand", "").strip(),
                            "images": getattr(content, "images", [])[:3],
                            "bullet_points": getattr(content, "bullet_points", [])[:5]
                            if getattr(content, "bullet_points", None)
                            else [],
                        }
                    )

            response_data = {
                "tool": "get_amazon_product",
                "asin": asin,
                "product_info": product_info,
            }

            log_info(f"Amazon product lookup completed for ASIN {asin}")
            return json.dumps(response_data, indent=2)

        except Exception as e:
            error_msg = f"Amazon product lookup failed: {str(e)}"
            log_error(error_msg)
            return self._error_response("get_amazon_product", error_msg, {"asin": asin})

    def search_amazon_products(self, query: str, domain_code: str = "com") -> str:
        """Search Amazon for products and return search results.

        Args:
            query: Product search query
            domain_code: Amazon domain (e.g., "com", "co.uk", "de", default: "com")

        Returns:
            JSON string with search results containing:
            - success: boolean indicating if search was successful
            - query: the original search query
            - total_products: number of products found
            - products: list of product results with title, asin, price, rating, etc.
        """
        try:
            if not query or not isinstance(query, str) or len(query.strip()) == 0:
                return self._error_response("search_amazon_products", "Query cannot be empty")

            if not isinstance(domain_code, str) or len(domain_code) > 10:
                return self._error_response(
                    "search_amazon_products", "Domain must be a valid string (e.g., 'com', 'co.uk')"
                )

            query = query.strip()
            log_info(f"Amazon search: '{query}' on amazon.{domain_code}")

            response: Response = self.client.amazon.scrape_search(query=query, domain=domain_code, parse=True)

            # Extract search results
            products = []

            if response.results and len(response.results) > 0:
                result = response.results[0]

                if hasattr(result, "content") and result.content:
                    content = result.content
                    if isinstance(content, dict) and "results" in content:
                        organic_results = content["results"].get("organic", [])

                        for item in organic_results:
                            products.append(
                                {
                                    "title": item.get("title", "").strip(),
                                    "asin": item.get("asin", "").strip(),
                                    "price": item.get("price", 0),
                                    "currency": item.get("currency", ""),
                                    "rating": item.get("rating", 0),
                                    "reviews_count": item.get("reviews_count", 0),
                                    "url": item.get("url", "").strip(),
                                    "position": item.get("pos", 0),
                                    "image": item.get("image", "").strip(),
                                }
                            )

                elif hasattr(result, "content_parsed") and result.content_parsed:
                    content = result.content_parsed
                    if hasattr(content, "results") and content.results:
                        if hasattr(content.results, "organic"):
                            organic_results = content.results.organic
                            for item in organic_results:
                                products.append(
                                    {
                                        "title": getattr(item, "title", "").strip(),
                                        "asin": getattr(item, "asin", "").strip(),
                                        "price": getattr(item, "price", 0),
                                        "currency": getattr(item, "currency", ""),
                                        "rating": getattr(item, "rating", 0),
                                        "reviews_count": getattr(item, "reviews_count", 0),
                                        "url": getattr(item, "url", "").strip(),
                                        "position": getattr(item, "pos", 0),
                                        "image": getattr(item, "image", "").strip(),
                                    }
                                )

            response_data = {
                "tool": "search_amazon_products",
                "query": query,
                "products": products,
            }

            log_debug(f"Amazon search completed. Found {len(products)} products")
            return json.dumps(response_data, indent=2)

        except Exception as e:
            error_msg = f"Amazon search failed: {str(e)}"
            log_error(error_msg)
            return self._error_response("search_amazon_products", error_msg, {"query": query})

    def scrape_website(self, url: str, render_javascript: bool = False) -> str:
        """Scrape content from any website URL.

        Args:
            url: Website URL to scrape (must start with http:// or ht   ps://)
            render_javascript: Whether to enable JavaScript rendering for dynamic content (default: False)

        Returns:
            JSON of results
        """
        try:
            if not url or not isinstance(url, str):
                return self._error_response("scrape_website", "URL is required and must be a string")

            url = url.strip()
            if not url.startswith(("http://", "https://")):
                return self._error_response(
                    "scrape_website", f"Invalid URL format: {url}. Must start with http:// or https://"
                )

            try:
                parsed_url = urlparse(url)
                if not parsed_url.netloc:
                    return self._error_response("scrape_website", f"Invalid URL format: {url}. Missing domain name")
            except Exception:
                return self._error_response("scrape_website", f"Invalid URL format: {url}")

            if not isinstance(render_javascript, bool):
                return self._error_response("scrape_website", "render_javascript must be a boolean (True/False)")

            log_debug(f"Website scraping: {url} (JS rendering: {render_javascript})")

            response: Response = self.client.universal.scrape_url(
                url=url, render=render.HTML if render_javascript else None, parse=True
            )

            content_info = {"url": url, "javascript_rendered": render_javascript}

            if response.results and len(response.results) > 0:
                result = response.results[0]
                content = result.content
                status_code = getattr(result, "status_code", None)

                content_preview = ""
                content_length = 0

                if content:
                    try:
                        content_str = str(content)
                        content_length = len(content_str)
                        content_preview = content_str[:1000] if content_length > 1000 else content_str
                        content_info["scraped"] = True
                    except Exception as e:
                        log_debug(f"Could not process content: {e}")
                        content_preview = "Content available but processing failed"
                        content_info["scraped"] = False

                content_info.update(
                    {
                        "status_code": status_code,
                        "content_length": content_length,
                        "content_preview": content_preview.strip(),
                        "has_content": content_length > 0,
                    }
                )

            response_data = {
                "tool": "scrape_website",
                "url": url,
                "content_info": content_info,
            }

            log_debug(f"Website scraping completed for {url}")
            return json.dumps(response_data, indent=2)

        except Exception as e:
            error_msg = f"Website scraping failed: {str(e)}"
            log_error(error_msg)
            return self._error_response("scrape_website", error_msg, {"url": url})

    def _error_response(self, tool_name: str, error_message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate a standardized error response."""
        error_data = {"tool": tool_name, "error": error_message, "context": context or {}}
        return json.dumps(error_data, indent=2)
