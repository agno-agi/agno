import httpx

from agno.tools import Toolkit
from agno.utils.log import logger


class WebTools(Toolkit):
    """
    A toolkit for working with web-related tools.
    """

    def __init__(self, retries: int = 3):
        super().__init__(name="web_tools")

        self.retries = retries

        self.register(self.expand_url)

    def expand_url(self, url: str) -> str:
        """
        Expands a shortened URL to its final destination using HTTP HEAD requests with retries.

        :param url: The URL to expand.

        :return: The final destination URL if successful; otherwise, returns the original URL.
        """
        timeout = 5
        for attempt in range(1, self.retries + 1):
            try:
                response = httpx.head(url, follow_redirects=True, timeout=timeout)
                final_url = response.url
                logger.info(f"expand_url: {url} expanded to {final_url} on attempt {attempt}")
                return str(final_url)
            except Exception as e:
                logger.error(f"Error expanding URL {url} on attempt {attempt}: {e}")

        return url
