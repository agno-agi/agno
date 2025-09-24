import json
from typing import Any, Callable, Dict, List, Optional, Set

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from trafilatura import (
        extract,
        extract_metadata,
        fetch_url,
        html2txt,
    )
    from trafilatura.meta import reset_caches

    # Import spider functionality
    try:
        from trafilatura.spider import focused_crawler

        SPIDER_AVAILABLE = True
    except ImportError:
        SPIDER_AVAILABLE = False
        logger.warning("Trafilatura spider module not available. Web crawling functionality will be disabled.")

except ImportError:
    raise ImportError("`trafilatura` not installed. Please install using `pip install trafilatura`")


class TrafilaturaTools(Toolkit):
    """
    TrafilaturaTools is a toolkit for web scraping and text extraction.

    Args:
        output_format (str): Default output format for extractions. Options: 'txt', 'json', 'xml', 'markdown', 'csv', 'html', 'xmltei'.
        include_comments (bool): Whether to extract comments along with main text by default.
        include_tables (bool): Whether to include table content by default.
        include_images (bool): Whether to include image information by default (experimental).
        include_formatting (bool): Whether to preserve formatting by default.
        include_links (bool): Whether to preserve links by default (experimental).
        with_metadata (bool): Whether to include metadata in extractions by default.
        favor_precision (bool): Whether to prefer precision over recall by default.
        favor_recall (bool): Whether to prefer recall over precision by default.
        target_language (Optional[str]): Default target language filter (ISO 639-1 format).
        deduplicate (bool): Whether to remove duplicate segments by default.
        max_tree_size (Optional[int]): Maximum tree size for processing.
        max_crawl_urls (int): Maximum number of URLs to crawl per website.
        max_known_urls (int): Maximum number of known URLs during crawling.
    """

    def __init__(
        self,
        output_format: str = "txt",
        include_comments: bool = True,
        include_tables: bool = True,
        include_images: bool = False,
        include_formatting: bool = False,
        include_links: bool = False,
        with_metadata: bool = False,
        favor_precision: bool = False,
        favor_recall: bool = False,
        target_language: Optional[str] = None,
        deduplicate: bool = False,
        max_tree_size: Optional[int] = None,
        max_crawl_urls: int = 10,
        max_known_urls: int = 100000,
        # Tool enable flags for <6 functions
        enable_extract_text: bool = True,
        enable_extract_metadata_only: bool = True,
        enable_html_to_text: bool = True,
        enable_extract_batch: bool = True,
        enable_crawl_website: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.output_format = output_format
        self.include_comments = include_comments
        self.include_tables = include_tables
        self.include_images = include_images
        self.include_formatting = include_formatting
        self.include_links = include_links
        self.with_metadata = with_metadata
        self.favor_precision = favor_precision
        self.favor_recall = favor_recall
        self.target_language = target_language
        self.deduplicate = deduplicate
        self.max_tree_size = max_tree_size
        self.max_crawl_urls = max_crawl_urls
        self.max_known_urls = max_known_urls

        tools: List[Callable] = []
        if all or enable_extract_text:
            tools.append(self.extract_text)
        if all or enable_extract_metadata_only:
            tools.append(self.extract_metadata_only)
        if all or enable_html_to_text:
            tools.append(self.html_to_text)
        if all or enable_extract_batch:
            tools.append(self.extract_batch)

        if all or enable_crawl_website:
            if not SPIDER_AVAILABLE:
                logger.warning("Web crawling requested but spider module not available. Skipping crawler tool.")
            else:
                tools.append(self.crawl_website)

        super().__init__(name="trafilatura_tools", tools=tools, **kwargs)

    def _get_extraction_params(
        self,
        output_format: Optional[str] = None,
        include_comments: Optional[bool] = None,
        include_tables: Optional[bool] = None,
        include_images: Optional[bool] = None,
        include_formatting: Optional[bool] = None,
        include_links: Optional[bool] = None,
        with_metadata: Optional[bool] = None,
        favor_precision: Optional[bool] = None,
        favor_recall: Optional[bool] = None,
        target_language: Optional[str] = None,
        deduplicate: Optional[bool] = None,
        max_tree_size: Optional[int] = None,
        url_blacklist: Optional[Set[str]] = None,
        author_blacklist: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Helper method to build extraction parameters with fallbacks to instance defaults."""
        return {
            "output_format": output_format if output_format is not None else self.output_format,
            "include_comments": include_comments if include_comments is not None else self.include_comments,
            "include_tables": include_tables if include_tables is not None else self.include_tables,
            "include_images": include_images if include_images is not None else self.include_images,
            "include_formatting": include_formatting if include_formatting is not None else self.include_formatting,
            "include_links": include_links if include_links is not None else self.include_links,
            "with_metadata": with_metadata if with_metadata is not None else self.with_metadata,
            "favor_precision": favor_precision if favor_precision is not None else self.favor_precision,
            "favor_recall": favor_recall if favor_recall is not None else self.favor_recall,
            "target_language": target_language if target_language is not None else self.target_language,
            "deduplicate": deduplicate if deduplicate is not None else self.deduplicate,
            "max_tree_size": max_tree_size if max_tree_size is not None else self.max_tree_size,
            "url_blacklist": url_blacklist,
            "author_blacklist": author_blacklist,
        }

    def extract_text(
        self,
        url: str,
        output_format: Optional[str] = None,
    ) -> str:
        """
        Extract main text content from a web page URL using Trafilatura.

        Args:
            url (str): The URL to extract content from.
            output_format (Optional[str]): Output format. Options: 'txt', 'json', 'xml', 'markdown', 'csv', 'html', 'xmltei'.

        Returns:
            str: Extracted content in the specified format, or error message if extraction fails.
        """
        try:
            log_debug(f"Extracting text from URL: {url}")

            # Fetch the webpage content
            html_content = fetch_url(url)
            if not html_content:
                return f"Error: Could not fetch content from URL: {url}"

            # Get extraction parameters
            params = self._get_extraction_params(output_format=output_format)

            result = extract(html_content, url=url, **params)

            if result is None:
                return f"Error: Could not extract readable content from URL: {url}"

            # Reset caches
            reset_caches()

            return result

        except Exception as e:
            logger.warning(f"Error extracting text from {url}: {e}")
            return f"Error extracting text from {url}: {e}"

    def extract_metadata_only(
        self,
        url: str,
        as_json: bool = True,
    ) -> str:
        """
        Extract only metadata from a web page URL.

        Args:
            url (str): The URL to extract metadata from.
            as_json (bool): Whether to return metadata as JSON string.

        Returns:
            str: Extracted metadata as JSON string or formatted text.
        """
        try:
            log_debug(f"Extracting metadata from URL: {url}")

            # Fetch the webpage content
            html_content = fetch_url(url)
            if not html_content:
                return f"Error: Could not fetch content from URL: {url}"

            # Extract metadata
            metadata_doc = extract_metadata(
                html_content,
                default_url=url,
                extensive=True,  # default
                author_blacklist=None,
            )

            if metadata_doc is None:
                return f"Error: Could not extract metadata from URL: {url}"

            metadata_dict = metadata_doc.as_dict()

            # Reset caches
            reset_caches()

            if as_json:
                return json.dumps(metadata_dict, indent=2, default=str)
            else:
                return "\n".join(f"{key}: {value}" for key, value in metadata_dict.items())

        except Exception as e:
            logger.warning(f"Error extracting metadata from {url}: {e}")
            return f"Error extracting metadata from {url}: {e}"

    def crawl_website(
        self,
        homepage_url: str,
        extract_content: bool = False,
    ) -> str:
        """
        Crawl a website and optionally extract content from discovered pages.

        Args:
            homepage_url (str): The starting URL (preferably homepage) to crawl from.
            extract_content (bool): Whether to extract content from discovered URLs.

        Returns:
            str: JSON containing crawl results and optionally extracted content.
        """
        if not SPIDER_AVAILABLE:
            return "Error: Web crawling functionality not available. Trafilatura spider module could not be imported."

        try:
            log_debug(f"Starting website crawl from: {homepage_url}")

            # Use instance configuration
            max_seen = self.max_crawl_urls
            max_known = self.max_known_urls
            lang = self.target_language

            # Perform focused crawling
            to_visit, known_links = focused_crawler(
                homepage=homepage_url,
                max_seen_urls=max_seen,
                max_known_urls=max_known,
                lang=lang,
            )

            crawl_results = {
                "homepage": homepage_url,
                "to_visit": list(to_visit) if to_visit else [],
                "known_links": list(known_links) if known_links else [],
                "stats": {
                    "urls_to_visit": len(to_visit) if to_visit else 0,
                    "known_links_count": len(known_links) if known_links else 0,
                },
            }

            # Optionally extract content from discovered URLs
            if extract_content and known_links:
                log_debug("Extracting content from discovered URLs")
                extracted_content = {}

                # Limit extraction to avoid overwhelming responses
                urls_to_extract = list(known_links)[: min(10, len(known_links))]

                for url in urls_to_extract:
                    try:
                        params = self._get_extraction_params()

                        html_content = fetch_url(url)
                        if html_content:
                            content = extract(html_content, url=url, **params)
                            if content:
                                extracted_content[url] = content
                    except Exception as e:
                        extracted_content[url] = f"Error extracting content: {e}"

                crawl_results["extracted_content"] = extracted_content

            # Reset caches
            reset_caches()

            return json.dumps(crawl_results, indent=2, default=str)

        except Exception as e:
            logger.warning(f"Error crawling website {homepage_url}: {e}")
            return f"Error crawling website {homepage_url}: {e}"

    def html_to_text(
        self,
        html_content: str,
        clean: bool = True,
    ) -> str:
        """
        Convert HTML content to plain text using Trafilatura's html2txt function.

        Args:
            html_content (str): The HTML content to convert.
            clean (bool): Whether to remove potentially undesirable elements.

        Returns:
            str: Plain text extracted from HTML.
        """
        try:
            log_debug("Converting HTML to text")

            result = html2txt(html_content, clean=clean)

            # Reset caches
            reset_caches()

            return result if result else "Error: Could not extract text from HTML content"

        except Exception as e:
            logger.warning(f"Error converting HTML to text: {e}")
            return f"Error converting HTML to text: {e}"

    def extract_batch(
        self,
        urls: List[str],
    ) -> str:
        """
        Extract content from multiple URLs in batch.

        Args:
            urls (List[str]): List of URLs to extract content from.

        Returns:
            str: JSON containing batch extraction results.
        """
        try:
            log_debug(f"Starting batch extraction for {len(urls)} URLs")

            results = {}
            failed_urls = []

            for url in urls:
                try:
                    params = self._get_extraction_params()

                    html_content = fetch_url(url)
                    if html_content:
                        content = extract(html_content, url=url, **params)
                        if content:
                            results[url] = content
                        else:
                            failed_urls.append(url)
                    else:
                        failed_urls.append(url)

                except Exception as e:
                    failed_urls.append(url)
                    results[url] = f"Error: {e}"

            # Reset caches after batch processing
            reset_caches()

            batch_results = {
                "successful_extractions": len(results)
                - len([k for k, v in results.items() if str(v).startswith("Error:")]),
                "failed_extractions": len(failed_urls),
                "total_urls": len(urls),
                "results": results,
                "failed_urls": failed_urls,
            }

            return json.dumps(batch_results, indent=2, default=str)

        except Exception as e:
            logger.warning(f"Error in batch extraction: {e}")
            return f"Error in batch extraction: {e}"
