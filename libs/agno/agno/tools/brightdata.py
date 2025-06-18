import base64
import json
from os import getenv
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed.")


class BrightDataTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        serp_zone: str = "serp_api",
        web_unlocker_zone: str = "web_unlocker1",
        scrape_as_markdown: bool = True,
        get_screenshot: bool = False,
        search_engine: bool = True,
        web_data_feed: bool = True,
        verbose: bool = False,
        timeout: int = 600,
        **kwargs,
    ):
        self.api_key = api_key or getenv("BRIGHT_DATA_API_KEY")
        if not self.api_key:
            log_error("No Bright Data API key provided")
            raise ValueError(
                "No Bright Data API key provided. Please provide an api_key or set the BRIGHT_DATA_API_KEY environment variable."
            )

        self.verbose = verbose
        self.endpoint = "https://api.brightdata.com/request"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        self.web_unlocker_zone = getenv("BRIGHT_DATA_WEB_UNLOCKER_ZONE", web_unlocker_zone)
        self.serp_zone = getenv("BRIGHT_DATA_SERP_ZONE", serp_zone)
        self.timeout = timeout

        tools: List[Any] = []

        if scrape_as_markdown:
            tools.append(self.scrape_as_markdown)
        if get_screenshot:
            tools.append(self.get_screenshot)
        if search_engine:
            tools.append(self.search_engine)
        if web_data_feed:
            tools.append(self.web_data_feed)

        super().__init__(name="brightdata_tools", tools=tools, **kwargs)

    def _make_request(self, payload: Dict) -> str:
        """Make a request to Bright Data API."""
        try:
            if self.verbose:
                log_info(f"[Bright Data] Request: {payload['url']}")

            response = requests.post(self.endpoint, headers=self.headers, data=json.dumps(payload))

            if response.status_code != 200:
                raise Exception(f"Failed to scrape: {response.status_code} - {response.text}")

            return response.text
        except Exception as e:
            raise Exception(f"Request failed: {e}")

    def scrape_as_markdown(self, url: str) -> str:
        """
        Scrape a webpage and return content in Markdown format.

        Args:
            url (str): URL to scrape

        Returns:
            str: Scraped content as Markdown
        """
        try:
            if not self.api_key:
                return "Please provide a Bright Data API key"
            if not url:
                return "Please provide a URL to scrape"

            log_info(f"Scraping URL as Markdown: {url}")

            payload = {
                "url": url,
                "zone": self.web_unlocker_zone,
                "format": "raw",
                "data_format": "markdown",
            }

            content = self._make_request(payload)
            return content
        except Exception as e:
            return f"Error scraping URL {url}: {e}"

    def get_screenshot(self, agent: Agent, url: str, output_path: str = "screenshot.png") -> str:
        """
        Capture a screenshot of a webpage

        Args:
            url (str): URL to screenshot

        Returns:
            str: A message indicating success (including media ID) or failure.
        """
        try:
            if not self.api_key:
                return "Please provide a Bright Data API key"
            if not url:
                return "Please provide a URL to screenshot"

            log_info(f"Taking screenshot of: {url}")

            payload = {
                "url": url,
                "zone": self.web_unlocker_zone,
                "format": "raw",
                "data_format": "screenshot",
            }

            response = requests.post(self.endpoint, headers=self.headers, data=json.dumps(payload))

            if response.status_code != 200:
                raise Exception(f"Error {response.status_code}: {response.text}")

            image_bytes = response.content
            base64_encoded_image = base64.b64encode(image_bytes).decode("utf-8")
            log_debug(f"Base64 encoded image: {type(base64_encoded_image)}")

            media_id = str(uuid4())

            agent.add_image(
                ImageArtifact(
                    id=media_id,
                    content=base64_encoded_image.encode("utf-8"),
                    mime_type="image/png",
                    original_prompt=f"Screenshot of {url}",
                )
            )
            log_debug(f"Screenshot captured and added as artifact with ID: {media_id}")
            return f"Screenshot captured and added as artifact with ID: {media_id}"
        except Exception as e:
            return f"Error taking screenshot of {url}: {e}"

    def search_engine(
        self,
        query: str,
        engine: str = "google",
        num_results: int = 10,
        language: Optional[str] = None,
        country_code: Optional[str] = None,
    ) -> str:
        """
        Search using Google, Bing, or Yandex and return results in Markdown.

        Args:
            query (str): Search query
            engine (str): Search engine - 'google', 'bing', or 'yandex'
            num_results (int): Number of results to return
            language (Optional[str]): Two-letter language code
            country_code (Optional[str]): Two-letter country code

        Returns:
            str: Search results as Markdown
        """
        try:
            if not self.api_key:
                return "Please provide a Bright Data API key"
            if not query:
                return "Please provide a query to search for"

            log_info(f"Searching {engine} for: {query}")

            from urllib.parse import quote

            encoded_query = quote(query)

            base_urls = {
                "google": f"https://www.google.com/search?q={encoded_query}",
                "bing": f"https://www.bing.com/search?q={encoded_query}",
                "yandex": f"https://yandex.com/search/?text={encoded_query}",
            }

            if engine not in base_urls:
                return f"Unsupported search engine: {engine}. Use 'google', 'bing', or 'yandex'"

            search_url = base_urls[engine]

            if engine == "google":
                params = []
                if language:
                    params.append(f"hl={language}")
                if country_code:
                    params.append(f"gl={country_code}")
                if num_results:
                    params.append(f"num={num_results}")

                if params:
                    search_url += "&" + "&".join(params)

            payload = {
                "url": search_url,
                "zone": self.serp_zone,
                "format": "raw",
                "data_format": "markdown",
            }

            content = self._make_request(payload)
            return content
        except Exception as e:
            return f"Error searching for query {query}: {e}"

    def web_data_feed(
        self,
        source_type: str,
        url: str,
        num_of_reviews: Optional[int] = None,
    ) -> str:
        """
        Retrieve structured web data from various sources like LinkedIn, Amazon, Instagram, etc.

        Args:
            source_type (str): Type of data source (e.g., 'linkedin_person_profile', 'amazon_product')
            url (str): URL of the web resource to retrieve data from
            num_of_reviews (Optional[int]): Number of reviews to retrieve

        Returns:
            str: Structured data from the requested source as JSON
        """
        try:
            if not self.api_key:
                return "Please provide a Bright Data API key"
            if not url:
                return "Please provide a URL to retrieve data from"

            log_info(f"Retrieving {source_type} data from: {url}")

            datasets = {
                "amazon_product": "gd_l7q7dkf244hwjntr0",
                "amazon_product_reviews": "gd_le8e811kzy4ggddlq",
                "amazon_product_search": "gd_lwdb4vjm1ehb499uxs",
                "walmart_product": "gd_l95fol7l1ru6rlo116",
                "walmart_seller": "gd_m7ke48w81ocyu4hhz0",
                "ebay_product": "gd_ltr9mjt81n0zzdk1fb",
                "homedepot_products": "gd_lmusivh019i7g97q2n",
                "zara_products": "gd_lct4vafw1tgx27d4o0",
                "etsy_products": "gd_ltppk0jdv1jqz25mz",
                "bestbuy_products": "gd_ltre1jqe1jfr7cccf",
                "linkedin_person_profile": "gd_l1viktl72bvl7bjuj0",
                "linkedin_company_profile": "gd_l1vikfnt1wgvvqz95w",
                "linkedin_job_listings": "gd_lpfll7v5hcqtkxl6l",
                "linkedin_posts": "gd_lyy3tktm25m4avu764",
                "linkedin_people_search": "gd_m8d03he47z8nwb5xc",
                "crunchbase_company": "gd_l1vijqt9jfj7olije",
                "zoominfo_company_profile": "gd_m0ci4a4ivx3j5l6nx",
                "instagram_profiles": "gd_l1vikfch901nx3by4",
                "instagram_posts": "gd_lk5ns7kz21pck8jpis",
                "instagram_reels": "gd_lyclm20il4r5helnj",
                "instagram_comments": "gd_ltppn085pokosxh13",
                "facebook_posts": "gd_lyclm1571iy3mv57zw",
                "facebook_marketplace_listings": "gd_lvt9iwuh6fbcwmx1a",
                "facebook_company_reviews": "gd_m0dtqpiu1mbcyc2g86",
                "facebook_events": "gd_m14sd0to1jz48ppm51",
                "tiktok_profiles": "gd_l1villgoiiidt09ci",
                "tiktok_posts": "gd_lu702nij2f790tmv9h",
                "tiktok_shop": "gd_m45m1u911dsa4274pi",
                "tiktok_comments": "gd_lkf2st302ap89utw5k",
                "google_maps_reviews": "gd_luzfs1dn2oa0teb81",
                "google_shopping": "gd_ltppk50q18kdw67omz",
                "google_play_store": "gd_lsk382l8xei8vzm4u",
                "apple_app_store": "gd_lsk9ki3u2iishmwrui",
                "reuter_news": "gd_lyptx9h74wtlvpnfu",
                "github_repository_file": "gd_lyrexgxc24b3d4imjt",
                "yahoo_finance_business": "gd_lmrpz3vxmz972ghd7",
                "x_posts": "gd_lwxkxvnf1cynvib9co",
                "zillow_properties_listing": "gd_lfqkr8wm13ixtbd8f5",
                "booking_hotel_listings": "gd_m5mbdl081229ln6t4a",
                "youtube_profiles": "gd_lk538t2k2p1k3oos71",
                "youtube_comments": "gd_lk9q0ew71spt1mxywf",
                "reddit_posts": "gd_lvz8ah06191smkebj4",
                "youtube_videos": "gd_m5mbdl081229ln6t4a",
            }

            if source_type not in datasets:
                valid_sources = ", ".join(datasets.keys())
                return f"Invalid source_type: {source_type}. Valid options are: {valid_sources}"

            dataset_id = datasets[source_type]

            request_data = {"url": url}
            if source_type == "facebook_company_reviews" and num_of_reviews is not None:
                request_data["num_of_reviews"] = str(num_of_reviews)

            trigger_response = requests.post(
                "https://api.brightdata.com/datasets/v3/trigger",
                params={"dataset_id": dataset_id, "include_errors": "true"},
                headers=self.headers,
                json=[request_data],
            )

            trigger_data = trigger_response.json()
            if not trigger_data.get("snapshot_id"):
                return "No snapshot ID returned from trigger request"

            snapshot_id = trigger_data["snapshot_id"]

            import time

            attempts = 0
            max_attempts = self.timeout

            while attempts < max_attempts:
                try:
                    snapshot_response = requests.get(
                        f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}",
                        params={"format": "json"},
                        headers=self.headers,
                    )

                    snapshot_data = snapshot_response.json()

                    if isinstance(snapshot_data, dict) and snapshot_data.get("status") == "running":
                        attempts += 1
                        time.sleep(1)
                        continue

                    return json.dumps(snapshot_data)

                except Exception:
                    attempts += 1
                    time.sleep(1)

            return f"Timeout after {max_attempts} seconds waiting for {source_type} data"

        except Exception as e:
            return f"Error retrieving {source_type} data from {url}: {e}"
