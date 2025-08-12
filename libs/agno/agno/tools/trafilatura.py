import json
from typing import Any, Dict, List, Optional, Set

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
        extract_text (bool): Whether to extract main text content from URLs.
        extract_metadata_only (bool): Whether to extract only metadata from URLs.
        crawl_website (bool): Whether to enable web crawling functionality.
        html_to_text (bool): Whether to enable basic HTML to text conversion.
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
        extract_text: bool = True,
        extract_metadata_only: bool = False,
        crawl_website: bool = False,
        html_to_text: bool = False,
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

        tools = []
        if extract_text:
            tools.append(self.extract_text)
        if extract_metadata_only:
            tools.append(self.extract_metadata_only)
        if crawl_website and SPIDER_AVAILABLE:
            tools.append(self.crawl_website)
        elif crawl_website and not SPIDER_AVAILABLE:
            logger.warning("Web crawling requested but spider module not available. Skipping crawler tool.")
        if html_to_text:
            tools.append(self.html_to_text)

        # Add batch processing
        tools.append(self.extract_batch)

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
    ) -> str:
        """
        Extract main text content from a web page URL using Trafilatura.

        Args:
            url (str): The URL to extract content from.
            output_format (Optional[str]): Output format. Options: 'txt', 'json', 'xml', 'markdown', 'csv', 'html', 'xmltei'.
            include_comments (Optional[bool]): Whether to extract comments along with main text.
            include_tables (Optional[bool]): Whether to include table content.
            include_images (Optional[bool]): Whether to include image information (experimental).
            include_formatting (Optional[bool]): Whether to preserve formatting.
            include_links (Optional[bool]): Whether to preserve links (experimental).
            with_metadata (Optional[bool]): Whether to include metadata in the output.
            favor_precision (Optional[bool]): Prefer less text but more accurate extraction.
            favor_recall (Optional[bool]): Prefer more text even when uncertain.
            target_language (Optional[str]): Target language filter (ISO 639-1 format, e.g., 'en', 'fr').
            deduplicate (Optional[bool]): Whether to remove duplicate segments.
            max_tree_size (Optional[int]): Maximum tree size for processing.
            url_blacklist (Optional[Set[str]]): Set of URLs to filter out.
            author_blacklist (Optional[Set[str]]): Set of author names to filter out.

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
            params = self._get_extraction_params(
                output_format=output_format,
                include_comments=include_comments,
                include_tables=include_tables,
                include_images=include_images,
                include_formatting=include_formatting,
                include_links=include_links,
                with_metadata=with_metadata,
                favor_precision=favor_precision,
                favor_recall=favor_recall,
                target_language=target_language,
                deduplicate=deduplicate,
                max_tree_size=max_tree_size,
                url_blacklist=url_blacklist,
                author_blacklist=author_blacklist,
            )

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
        extensive: bool = True,
        author_blacklist: Optional[Set[str]] = None,
        as_json: bool = True,
    ) -> str:
        """
        Extract only metadata from a web page URL.

        Args:
            url (str): The URL to extract metadata from.
            extensive (bool): Whether to perform extensive metadata extraction.
            author_blacklist (Optional[Set[str]]): Set of author names to filter out.
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
                extensive=extensive,
                author_blacklist=author_blacklist,
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
        max_seen_urls: Optional[int] = None,
        max_known_urls: Optional[int] = None,
        target_language: Optional[str] = None,
        extract_content: bool = False,
        output_format: Optional[str] = None,
        include_metadata: bool = True,
    ) -> str:
        """
        Crawl a website and optionally extract content from discovered pages.

        Args:
            homepage_url (str): The starting URL (preferably homepage) to crawl from.
            max_seen_urls (Optional[int]): Maximum number of pages to visit. Defaults to instance setting.
            max_known_urls (Optional[int]): Maximum number of pages to "know" about. Defaults to instance setting.
            target_language (Optional[str]): Target language for link filtering (ISO 639-1 format).
            extract_content (bool): Whether to extract content from discovered URLs.
            output_format (Optional[str]): Output format for content extraction if enabled.
            include_metadata (bool): Whether to include metadata when extracting content.

        Returns:
            str: JSON containing crawl results and optionally extracted content.
        """
        if not SPIDER_AVAILABLE:
            return "Error: Web crawling functionality not available. Trafilatura spider module could not be imported."

        try:
            log_debug(f"Starting website crawl from: {homepage_url}")

            # Use instance defaults if not specified
            max_seen = max_seen_urls if max_seen_urls is not None else self.max_crawl_urls
            max_known = max_known_urls if max_known_urls is not None else self.max_known_urls
            lang = target_language if target_language is not None else self.target_language

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
                        params = self._get_extraction_params(
                            output_format=output_format,
                            with_metadata=include_metadata,
                        )

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
        output_format: Optional[str] = None,
        include_metadata: bool = True,
    ) -> str:
        """
        Extract content from multiple URLs in batch.

        Args:
            urls (List[str]): List of URLs to extract content from.
            output_format (Optional[str]): Output format for extractions.
            include_metadata (bool): Whether to include metadata in extractions.

        Returns:
            str: JSON containing batch extraction results.
        """
        try:
            log_debug(f"Starting batch extraction for {len(urls)} URLs")

            results = {}
            failed_urls = []

            for url in urls:
                try:
                    params = self._get_extraction_params(
                        output_format=output_format,
                        with_metadata=include_metadata,
                    )

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

    def get_supported_formats(self) -> List[str]:
        """
        Get list of supported output formats.

        Returns:
            List[str]: List of supported output formats.
        """
        return ["txt", "json", "xml", "markdown", "csv", "html", "xmltei"]

    def validate_language_code(self, language_code: str) -> bool:
        """
        Validate if language code is in ISO 639-1 format.

        Args:
            language_code (str): Language code to validate.

        Returns:
            bool: True if valid, False otherwise.
        """
        # Basic validation for ISO 639-1 (2-letter codes)
        return len(language_code) == 2 and language_code.isalpha()
