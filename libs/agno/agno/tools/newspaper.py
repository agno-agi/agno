from typing import Optional

from agno.tools import Toolkit
from agno.utils.functions import cache_result
from agno.utils.log import log_debug

try:
    from newspaper import Article
except ImportError:
    raise ImportError("`newspaper3k` not installed. Please run `pip install newspaper3k lxml_html_clean`.")


class NewspaperTools(Toolkit):
    """
    Newspaper is a tool for getting the text of an article from a URL.
    Args:
        get_article_text (bool): Whether to get the text of an article from a URL.
        cache_results (bool): Whether to enable caching of search results.
        cache_ttl (int): Time-to-live for cached results in seconds.
        cache_dir (Optional[str]): Directory to store cache files.
    """

    def __init__(
        self,
        get_article_text: bool = True,
        cache_results: bool = False,
        cache_ttl: int = 3600,
        cache_dir: Optional[str] = None,
    ):
        super().__init__(name="newspaper_toolkit")

        if get_article_text:
            self.register(self.get_article_text)

        self.cache_results = cache_results
        self.cache_ttl = cache_ttl
        self.cache_dir = cache_dir

    @cache_result()
    def get_article_text(self, url: str) -> str:
        """Get the text of an article from a URL.

        Args:
            url (str): The URL of the article.

        Returns:
            str: The text of the article.
        """

        try:
            log_debug(f"Reading news: {url}")
            article = Article(url)
            article.download()
            article.parse()
            return article.text
        except Exception as e:
            return f"Error getting article text from {url}: {e}"
