import json
from typing import Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_warning

try:
    import newspaper
except ImportError:
    raise ImportError("`newspaper4k` not installed. Please run `pip install newspaper4k lxml_html_clean`.")


class Newspaper4kTools(Toolkit):
    """Toolkit for extracting article content from URLs using newspaper4k."""

    def __init__(
        self,
        include_summary: bool = False,
        article_length: Optional[int] = None,
        read_article: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize Newspaper4k toolkit.

        Args:
            include_summary: Whether to include article summary in output.
            article_length: Max characters to return from article text. None for full.
            read_article: Enable the read_article tool.
            all: Enable all tools.
        """
        self.include_summary: bool = include_summary
        self.article_length: Optional[int] = article_length

        tools: List[Callable] = []
        if all or read_article:
            tools.append(self.read_article)

        super().__init__(name="newspaper4k_tools", tools=tools, **kwargs)

    def get_article_data(self, url: str) -> Optional[Dict[str, object]]:
        """Read and get article data from a URL.

        Args:
            url: The URL of the article.

        Returns:
            Dict with title, authors, text, and optionally summary/publish_date.
        """

        try:
            article = newspaper.article(url)
            article_data = {}
            if article.title:
                article_data["title"] = article.title
            if article.authors:
                article_data["authors"] = article.authors
            if article.text:
                article_data["text"] = article.text
            if self.include_summary and article.summary:
                article_data["summary"] = article.summary

            try:
                if article.publish_date:
                    article_data["publish_date"] = article.publish_date.isoformat() if article.publish_date else None
            except Exception:
                pass

            return article_data
        except Exception as e:
            log_warning(f"Error reading article from {url}: {str(e)}")
            return None

    def read_article(self, url: str) -> str:
        """Read and extract content from an article URL.

        Args:
            url: The URL of the article.

        Returns:
            JSON with title, authors, text, and optionally summary/publish_date.
        """
        try:
            log_debug(f"Reading news: {url}")
            article_data = self.get_article_data(url)
            if not article_data:
                return json.dumps({"error": f"No data found for {url}"})

            if self.article_length and "text" in article_data:
                article_data["text"] = article_data["text"][: self.article_length]

            return json.dumps(article_data)
        except Exception as e:
            return json.dumps({"error": f"Error reading article from {url}: {e}"})
