import json
from typing import Callable, List

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from newspaper import Article
except ImportError:
    raise ImportError("`newspaper3k` not installed. Please run `pip install newspaper3k lxml_html_clean`.")


class NewspaperTools(Toolkit):
    def __init__(
        self,
        get_article_text: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize the NewspaperTools toolkit.

        Args:
            get_article_text: Enable the get_article_text tool.
            all: Enable all tools regardless of individual flags.
            **kwargs: Additional arguments passed to the Toolkit base class.
        """
        tools: List[Callable] = []
        if all or get_article_text:
            tools.append(self.get_article_text)

        super().__init__(name="newspaper_toolkit", tools=tools, **kwargs)

    def get_article_text(self, url: str) -> str:
        """Get the text of an article from a URL.

        Args:
            url: The URL of the article.

        Returns:
            JSON object with text content or error message.
        """
        try:
            log_debug(f"Reading news: {url}")
            article = Article(url)
            article.download()
            article.parse()
            return json.dumps({"text": article.text})
        except Exception as e:
            return json.dumps({"error": f"Error getting article text from {url}: {e}"})
