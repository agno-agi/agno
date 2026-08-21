import json
from typing import Callable, List

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_exception, log_info


class WebTools(Toolkit):
    """Toolkit for web utilities like URL expansion.

    Args:
        retries: Number of retry attempts. Defaults to 3.
        expand_url: Enable expand_url tool. Defaults to True.
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        retries: int = 3,
        expand_url: bool = True,
        all: bool = False,
        **kwargs,
    ):
        # Backwards compat: enable_X -> X
        if "enable_expand_url" in kwargs:
            expand_url = kwargs.pop("enable_expand_url")

        self.retries = retries

        tools: List[Callable] = []
        if all or expand_url:
            tools.append(self.expand_url)

        super().__init__(name="web_tools", tools=tools, **kwargs)

    def expand_url(self, url: str) -> str:
        """Expand a shortened URL to its final destination.

        Args:
            url: The URL to expand.

        Returns:
            JSON with the final destination URL or original on failure.
        """
        timeout = 5
        for attempt in range(1, self.retries + 1):
            try:
                response = httpx.head(url, follow_redirects=True, timeout=timeout)
                final_url = str(response.url)
                log_info(f"expand_url: {url} expanded to {final_url} on attempt {attempt}")
                return json.dumps({"original_url": url, "expanded_url": final_url})
            except Exception:
                log_exception(f"Error expanding URL {url} on attempt {attempt}")

        return json.dumps({"original_url": url, "expanded_url": url, "error": "Failed after retries"})
