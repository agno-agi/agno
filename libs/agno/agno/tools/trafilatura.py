import json
from typing import Any, Callable, Dict, List, Optional, Set

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_warning

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
    except ImportError as e:
        SPIDER_AVAILABLE = False
        log_warning(f"Trafilatura spider module not available. Web crawling functionality will be disabled.: {str(e)}")


except ImportError:
    raise ImportError("`trafilatura` not installed. Please install using `pip install trafilatura`")


class TrafilaturaTools(Toolkit):
    """Toolkit for web scraping and text extraction using Trafilatura.

    Args:
        output_format: Default output format. Options: txt, json, xml, markdown, csv, html, xmltei.
        include_comments: Extract comments along with main text.
        include_tables: Include table content.
        include_images: Include image information (experimental).
        include_formatting: Preserve formatting.
        include_links: Preserve links (experimental).
        with_metadata: Include metadata in extractions.
        favor_precision: Prefer precision over recall.
        favor_recall: Prefer recall over precision.
        target_language: Target language filter (ISO 639-1 format).
        deduplicate: Remove duplicate segments.
        max_tree_size: Maximum tree size for processing.
        max_crawl_urls: Maximum number of URLs to crawl per website.
        max_known_urls: Maximum number of known URLs during crawling.
        scrape: Enable scrape tool (fetch URL, extract text). Defaults to True (token heavy).
        get_metadata: Enable get_metadata tool. Defaults to True (token heavy).
        convert_html: Enable convert_html tool (local HTML to text). Defaults to True.
        scrape_batch: Enable scrape_batch tool. Defaults to True (token heavy).
        crawl: Enable crawl tool (spider a website). Defaults to True (token heavy).
        all: Enable all tools. Defaults to False.
    """

    # Agno 2.x kwarg names accepted for backwards compatibility
    _legacy_param_aliases = {
        "enable_extract_text": "scrape",
        "enable_extract_metadata_only": "get_metadata",
        "enable_html_to_text": "convert_html",
        "enable_extract_batch": "scrape_batch",
        "enable_crawl_website": "crawl",
    }

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
        scrape: bool = True,
        get_metadata: bool = True,
        convert_html: bool = True,
        scrape_batch: bool = True,
        crawl: bool = True,
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
        if all or scrape:
            tools.append(self.scrape)
        if all or get_metadata:
            tools.append(self.get_metadata)
        if all or convert_html:
            tools.append(self.convert_html)
        if all or scrape_batch:
            tools.append(self.scrape_batch)

        if all or crawl:
            if not SPIDER_AVAILABLE:
                log_warning("Web crawling requested but spider module not available. Skipping crawler tool.")
            else:
                tools.append(self.crawl)

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

    def scrape(
        self,
        url: str,
        output_format: Optional[str] = None,
    ) -> str:
        """Scrape and extract main text content from a URL.

        Args:
            url: The URL to scrape.
            output_format: Output format (txt, json, xml, markdown, csv, html, xmltei).

        Returns:
            Extracted content or error message.
        """
        try:
            log_debug(f"Extracting text from URL: {url}")

            # Fetch the webpage content
            html_content = fetch_url(url)
            if not html_content:
                return json.dumps({"error": f"Could not fetch content from URL: {url}"})

            # Get extraction parameters
            params = self._get_extraction_params(output_format=output_format)

            result = extract(html_content, url=url, **params)

            if result is None:
                return json.dumps({"error": f"Could not extract readable content from URL: {url}"})

            # Reset caches
            reset_caches()

            return result

        except Exception as e:
            log_warning(f"Error extracting text from {url}: {str(e)}")
            return json.dumps({"error": f"Error extracting text from {url}: {e}"})

    def get_metadata(
        self,
        url: str,
        as_json: bool = True,
    ) -> str:
        """Extract metadata (title, author, date) from a URL.

        Args:
            url: The URL to extract metadata from.
            as_json: Return as JSON string. Defaults to True.

        Returns:
            Metadata as JSON or formatted text.
        """
        try:
            log_debug(f"Extracting metadata from URL: {url}")

            # Fetch the webpage content
            html_content = fetch_url(url)
            if not html_content:
                return json.dumps({"error": f"Could not fetch content from URL: {url}"})

            # Extract metadata
            metadata_doc = extract_metadata(
                html_content,
                default_url=url,
                extensive=True,
                author_blacklist=None,
            )

            if metadata_doc is None:
                return json.dumps({"error": f"Could not extract metadata from URL: {url}"})

            metadata_dict = metadata_doc.as_dict()

            # Reset caches
            reset_caches()

            if as_json:
                return json.dumps(metadata_dict, indent=2, default=str)
            else:
                return "\n".join(f"{key}: {value}" for key, value in metadata_dict.items())

        except Exception as e:
            log_warning(f"Error extracting metadata from {url}: {str(e)}")
            return json.dumps({"error": f"Error extracting metadata from {url}: {e}"})

    def crawl(
        self,
        homepage_url: str,
        extract_content: bool = False,
    ) -> str:
        """Crawl a website and optionally extract content from discovered pages.

        Args:
            homepage_url: The starting URL to crawl from.
            extract_content: Extract content from discovered URLs. Defaults to False.

        Returns:
            JSON with crawl results and optionally extracted content.
        """
        if not SPIDER_AVAILABLE:
            return json.dumps({"error": "Web crawling not available. Trafilatura spider module not installed."})

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
            log_warning(f"Error crawling website {homepage_url}: {str(e)}")
            return json.dumps({"error": f"Error crawling website {homepage_url}: {e}"})

    def convert_html(
        self,
        html_content: str,
        clean: bool = True,
    ) -> str:
        """Convert HTML content to plain text.

        Args:
            html_content: The HTML content to convert.
            clean: Remove undesirable elements. Defaults to True.

        Returns:
            Plain text extracted from HTML.
        """
        try:
            log_debug("Converting HTML to text")

            result = html2txt(html_content, clean=clean)

            # Reset caches
            reset_caches()

            return result if result else json.dumps({"error": "Could not extract text from HTML content"})

        except Exception as e:
            log_warning(f"Error converting HTML to text: {str(e)}")
            return json.dumps({"error": f"Error converting HTML to text: {e}"})

    def scrape_batch(
        self,
        urls: List[str],
    ) -> str:
        """Scrape and extract content from multiple URLs.

        Args:
            urls: List of URLs to scrape.

        Returns:
            JSON with batch extraction results.
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
            log_warning(f"Error in batch extraction: {str(e)}")
            return json.dumps({"error": f"Error in batch extraction: {e}"})
