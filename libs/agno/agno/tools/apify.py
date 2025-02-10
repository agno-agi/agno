from os import getenv
from typing import List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from apify_client import ApifyClient
except ImportError:
    raise ImportError("`apify_client` not installed. Please install using `pip install apify-client`")


class ApifyTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        website_content_crawler: bool = True,
        web_scraper: bool = False,
    ):
        super().__init__(name="apify_tools")

        self.api_key = api_key or getenv("MY_APIFY_TOKEN")
        if not self.api_key:
            logger.error("No Apify API key provided")

        if website_content_crawler:
            self.register(self.website_content_crawler)
        if web_scraper:
            self.register(self.web_scrapper)

    def website_content_crawler(self, urls: List[str], timeout: Optional[int] = 60) -> str:
        """
        Crawls a website using Apify's website-content-crawler actor.

        :param urls: The URLs to crawl.
        :param timeout: The timeout for the crawling.

        :return: The results of the crawling.
        """
        if self.api_key is None:
            return "No API key provided"

        if urls is None:
            return "No URLs provided"

        client = ApifyClient(self.api_key)

        logger.debug(f"Crawling URLs: {urls}")

        formatted_urls = [{"url": url} for url in urls]

        run_input = {"startUrls": formatted_urls}

        run = client.actor("apify/website-content-crawler").call(run_input=run_input, timeout_secs=timeout)

        results: str = ""

        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            results += "Results for URL: " + item.get("url") + "\n"
            results += item.get("text") + "\n"

        return results

    def web_scrapper(self, urls: List[str], timeout: Optional[int] = 60) -> str:
        """
        Scrapes a website using Apify's web-scraper actor.

        :param urls: The URLs to scrape.
        :param timeout: The timeout for the scraping.

        :return: The results of the scraping.
        """
        if self.api_key is None:
            return "No API key provided"

        if urls is None:
            return "No URLs provided"

        client = ApifyClient(self.api_key)

        logger.debug(f"Scrapping URLs: {urls}")

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

        results: str = ""

        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            results += "Results for URL: " + item.get("url") + "\n"
            results += item.get("pageTitle") + "\n"
            results += item.get("h1") + "\n"
            results += item.get("first_h2") + "\n"
            results += item.get("random_text_from_the_page") + "\n"

        return results
