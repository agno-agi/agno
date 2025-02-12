import json
from os import getenv
from typing import Optional
import requests
from unstructured.partition.html import partition_html
from agno.tools import Toolkit
from agno.utils.log import logger

class BrowserlessTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        website_url: Optional[str] = None,
    ):
        super().__init__(name="browserless")
        self.api_key = api_key or getenv("BROWSERLESS_API_KEY")
        if not self.api_key:
            logger.error("BROWSERLESS_API_KEY not set. Please set the BROWSERLESS_API_KEY environment variable.")
        self.website_url = website_url
        self.register(self.scrape_website)
        
    def scrape_website(self, website_url: str) -> str:
        """
        Use this function to scrape a website.
        """
        url = f"https://chrome.browserless.io/content?token={self.api_key}"
        web_url = self.website_url or website_url
        if not web_url:
            logger.error("Website URL not provided.")
            return "Please provide a website URL."
        payload = json.dumps({"url": web_url})
        headers = {"cache-control": "no-cache", "content-type": "application/json"}
        response = requests.request("POST", url, headers=headers, data=payload)
        content = partition_html(response.text)
        return content
