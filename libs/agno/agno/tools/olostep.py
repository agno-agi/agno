"""Olostep toolkit for Agno agents."""

import json
import os
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from olostep import Olostep, Olostep_BaseError
except ImportError:
    raise ImportError("`olostep` not installed. Please install using `pip install olostep`")


class OlostepTools(Toolkit):
    """
    Olostep is a toolkit for web scraping, crawling, mapping, search,
    and AI-powered answers for use in Agno agents.

    Args:
        api_key (Optional[str]): Olostep API key. Falls back to OLOSTEP_API_KEY env var.
        scrape_url (bool): Enable single-URL scraping. Default: True.
        crawl_website (bool): Enable website crawling. Default: False.
        map_website (bool): Enable URL discovery / site mapping. Default: False.
        search_web (bool): Enable web search returning structured links. Default: False.
        answer_question (bool): Enable AI-powered answers grounded in live web data. Default: False.
        batch_scrape (bool): Enable concurrent batch scraping of multiple URLs. Default: False.
        all_tools (bool): Enable all tools at once. Default: False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        scrape_url: bool = True,
        crawl_website: bool = False,
        map_website: bool = False,
        search_web: bool = False,
        answer_question: bool = False,
        batch_scrape: bool = False,
        all_tools: bool = False,
    ) -> None:
        super().__init__(name="olostep")

        self.api_key = api_key or os.getenv("OLOSTEP_API_KEY")
        if not self.api_key:
            log_error("OLOSTEP_API_KEY not set. Please set the OLOSTEP_API_KEY environment variable.")

        self.client = Olostep(api_key=self.api_key)

        if all_tools:
            scrape_url = crawl_website = map_website = True
            search_web = answer_question = batch_scrape = True

        if scrape_url:
            self.register(self.scrape_url)
        if crawl_website:
            self.register(self.crawl_website)
        if map_website:
            self.register(self.map_website)
        if search_web:
            self.register(self.search_web)
        if answer_question:
            self.register(self.answer_question)
        if batch_scrape:
            self.register(self.batch_scrape)

    def scrape_url(
        self,
        url: str,
        formats: str = "markdown",
        wait_before_scraping: int = 0,
        remove_images: bool = False,
        country: Optional[str] = None,
        parser_id: Optional[str] = None,
        llm_extract_prompt: Optional[str] = None,
        llm_extract_schema: Optional[str] = None,
    ) -> str:
        """
        Scrape a single URL and return its content.

        Use this to extract the text, markdown, HTML, or structured JSON from any webpage.
        Supports JS-rendered sites. For structured extraction, use parser_id (efficient,
        for known sites) or llm_extract_prompt/llm_extract_schema (flexible, costs more).

        Args:
            url: The full URL to scrape (e.g. "https://example.com/page").
            formats: Comma-separated output formats. Options: "markdown" (default,
                     LLM-friendly), "html" (cleaned HTML), "text" (plain text),
                     "json" (structured — requires parser_id or llm_extract_schema/prompt).
            wait_before_scraping: Milliseconds to wait after page load before extracting.
                                  Useful for JS-heavy or dynamic pages.
            remove_images: Strip image tags from the output. Default: False.
            country: Two-letter country code for geo-location simulation (e.g. "us", "gb").
            parser_id: Olostep pre-built parser ID for structured JSON extraction.
                       Available parsers: "@olostep/google-search", "@olostep/amazon-it-product",
                       "@olostep/extract-emails", "@olostep/extract-socials",
                       "@olostep/extract-calendars". Include "json" in formats when using this.
            llm_extract_prompt: Natural language instruction for LLM-based structured
                                extraction (e.g. "Extract the event title, date, and venue").
                                Costs 20 credits. Include "json" in formats.
            llm_extract_schema: JSON string schema for LLM extraction
                                (e.g. '{"title": "", "date": "", "venue": ""}').
                                Takes precedence over llm_extract_prompt if both provided.

        Returns:
            Scraped content as a string. Returns markdown/text/html directly.
            Returns JSON string when using parser or llm_extract.
            Returns an error message string on failure.
        """
        try:
            fmt_list = [f.strip() for f in formats.split(",")]

            kwargs: Dict[str, Any] = {
                "url_to_scrape": url,
                "formats": fmt_list,
                "wait_before_scraping": wait_before_scraping,
                "remove_images": remove_images,
            }

            if country:
                kwargs["country"] = country.lower()

            if parser_id:
                kwargs["parser"] = {"id": parser_id}

            if llm_extract_schema:
                try:
                    schema = json.loads(llm_extract_schema)
                except json.JSONDecodeError:
                    return "Error: llm_extract_schema must be a valid JSON string."
                kwargs["llm_extract"] = {"schema": schema}
            elif llm_extract_prompt:
                kwargs["llm_extract"] = {"prompt": llm_extract_prompt}

            result = self.client.scrapes.create(**kwargs)

            if "json" in fmt_list and result.json_content:
                return result.json_content
            if "markdown" in fmt_list and result.markdown_content:
                return result.markdown_content
            if "text" in fmt_list and result.text_content:
                return result.text_content
            if "html" in fmt_list and result.html_content:
                return result.html_content

            return "No content returned for the requested formats."

        except Olostep_BaseError as e:
            return f"Olostep API error scraping {url}: {type(e).__name__}: {e}"
        except Exception as e:
            return f"Unexpected error scraping {url}: {e}"

    def crawl_website(
        self,
        url: str,
        max_pages: int = 20,
        max_depth: Optional[int] = None,
        include_urls: Optional[str] = None,
        exclude_urls: Optional[str] = None,
        search_query: Optional[str] = None,
        top_n: Optional[int] = None,
    ) -> str:
        """
        Crawl a website starting from a URL and return content from all crawled pages.

        Use this to gather content from an entire website or a section of it — for example,
        all blog posts, all docs pages, or all product listings. Supports URL glob filtering
        and relevance-based filtering via search_query.

        Args:
            url: The starting URL for the crawl (e.g. "https://docs.example.com").
            max_pages: Maximum number of pages to crawl. Default: 20. Max: 1000.
            max_depth: Maximum link depth from the start URL. None means no depth limit.
            include_urls: Comma-separated glob patterns for paths to include
                          (e.g. "/blog/**, /articles/**"). Only matching URLs are crawled.
            exclude_urls: Comma-separated glob patterns for paths to exclude
                          (e.g. "/admin/**, /login/**").
            search_query: Filter crawled pages by relevance to this query
                          (e.g. "pricing information"). Returns most relevant pages first.
            top_n: When combined with search_query, limits to top N most relevant pages.

        Returns:
            JSON string — a list of objects with "url" and "markdown_content" fields.
            Returns an error message string on failure.
        """
        try:
            kwargs: Dict[str, Any] = {
                "start_url": url,
                "max_pages": max_pages,
            }

            if max_depth is not None:
                kwargs["max_depth"] = max_depth
            if include_urls:
                kwargs["include_urls"] = [p.strip() for p in include_urls.split(",")]
            if exclude_urls:
                kwargs["exclude_urls"] = [p.strip() for p in exclude_urls.split(",")]
            if search_query:
                kwargs["search_query"] = search_query
            if top_n is not None:
                kwargs["top_n"] = top_n

            crawl = self.client.crawls.create(**kwargs)

            pages: List[Dict[str, str]] = []
            for page in crawl.pages():
                try:
                    content = page.retrieve(["markdown"])
                    pages.append({
                        "url": page.url,
                        "markdown_content": content.markdown_content or "",
                    })
                except Exception as page_err:
                    log_error(f"Failed to retrieve content for {page.url}: {page_err}")
                    pages.append({"url": page.url, "markdown_content": ""})

            return json.dumps(pages, ensure_ascii=False)

        except Olostep_BaseError as e:
            return f"Olostep API error crawling {url}: {type(e).__name__}: {e}"
        except Exception as e:
            return f"Unexpected error crawling {url}: {e}"

    def map_website(
        self,
        url: str,
        include_urls: Optional[str] = None,
        exclude_urls: Optional[str] = None,
        include_subdomain: bool = False,
        top_n: Optional[int] = None,
    ) -> str:
        """
        Discover and return all URLs found on a website.

        Use this to explore a site's structure before scraping, or to prepare a URL
        list for batch_scrape. Returns URLs from sitemaps and discovered links.
        Ideal for SEO analysis, content discovery, and understanding site structure.

        Args:
            url: The website URL to map (e.g. "https://www.example.com").
            include_urls: Comma-separated glob path patterns to include
                          (e.g. "/product, /product/**").
            exclude_urls: Comma-separated glob path patterns to exclude
                          (e.g. "/ads/**, /tracking/**").
            include_subdomain: Also include URLs from subdomains (e.g. blog.example.com).
                               Default: False.
            top_n: Limit number of URLs returned. Default: all (up to ~100k).

        Returns:
            JSON string — a list of URL strings.
            Returns an error message string on failure.
        """
        try:
            kwargs: Dict[str, Any] = {"url": url}

            if include_urls:
                kwargs["include_urls"] = [p.strip() for p in include_urls.split(",")]
            if exclude_urls:
                kwargs["exclude_urls"] = [p.strip() for p in exclude_urls.split(",")]
            if include_subdomain:
                kwargs["include_subdomain"] = True
            if top_n is not None:
                kwargs["top_n"] = top_n

            maps = self.client.maps.create(**kwargs)

            urls: List[str] = []
            for u in maps.urls():
                urls.append(u)

            return json.dumps(urls, ensure_ascii=False)

        except Olostep_BaseError as e:
            return f"Olostep API error mapping {url}: {type(e).__name__}: {e}"
        except Exception as e:
            return f"Unexpected error mapping {url}: {e}"

    def search_web(self, query: str) -> str:
        """
        Search the web with a natural language query and return relevant links.

        Use this to find web pages on a topic before scraping them, or when you need a
        list of sources. Unlike answer_question (which returns a synthesized AI answer),
        this returns raw links for further investigation.

        Args:
            query: Natural language search query
                   (e.g. "best open source vector databases 2025").

        Returns:
            JSON string — a list of objects each with "url", "title", and "description".
            Returns an error message string on failure.
        """
        try:
            result = self.client.searches.create(query=query)

            links: List[Dict[str, str]] = []
            if result.result and result.result.links:
                for link in result.result.links:
                    links.append({
                        "url": link.url or "",
                        "title": link.title or "",
                        "description": link.description or "",
                    })

            return json.dumps(links, ensure_ascii=False)

        except Olostep_BaseError as e:
            return f"Olostep API error searching '{query}': {type(e).__name__}: {e}"
        except Exception as e:
            return f"Unexpected error searching '{query}': {e}"

    def answer_question(
        self,
        task: str,
        json_schema: Optional[str] = None,
    ) -> str:
        """
        Search the web and return an AI-powered answer grounded in live data.

        Use this for research tasks, fact-checking, or data enrichment where you need a
        synthesized answer with sources — not just raw links. Olostep searches the web,
        validates sources, and returns a structured answer. If data cannot be verified,
        it returns "NOT_FOUND" for that field.

        Args:
            task: The question or research task in natural language. Can reference
                  specific URLs (e.g. "What is the pricing at https://example.com?")
                  or ask general questions (e.g. "What is the current valuation of OpenAI?").
            json_schema: Optional JSON string defining the structure of the answer.
                         Provide an object with empty string values as a template
                         (e.g. '{"company_name": "", "valuation": "", "founded": ""}').
                         If omitted, returns a plain text answer.

        Returns:
            If json_schema provided: JSON string with structured answer plus "_sources" list.
            Otherwise: JSON string with "answer" (text) and "sources" (list of URLs).
            Returns an error message string on failure.
        """
        try:
            kwargs: Dict[str, Any] = {"task": task}

            if json_schema:
                try:
                    schema = json.loads(json_schema)
                    kwargs["json"] = schema
                except json.JSONDecodeError:
                    return "Error: json_schema must be a valid JSON string."

            answer = self.client.answers.create(**kwargs)

            if json_schema and answer.result and answer.result.json_content:
                try:
                    data = json.loads(answer.result.json_content)
                    json_sources = answer.result.sources if answer.result.sources else []
                    data["_sources"] = json_sources
                    return json.dumps(data, ensure_ascii=False)
                except json.JSONDecodeError:
                    return answer.result.json_content

            plain = answer.answer or ""
            sources: List[str] = []
            if answer.result and answer.result.sources:
                sources = answer.result.sources

            return json.dumps({"answer": plain, "sources": sources}, ensure_ascii=False)

        except Olostep_BaseError as e:
            return f"Olostep API error for task '{task}': {type(e).__name__}: {e}"
        except Exception as e:
            return f"Unexpected error for task '{task}': {e}"

    def batch_scrape(
        self,
        urls: str,
        formats: str = "markdown",
        parser_id: Optional[str] = None,
        country: Optional[str] = None,
    ) -> str:
        """
        Scrape multiple URLs concurrently in a single batch job.

        Use this when you have a list of URLs (50–10,000) to scrape at once. Processing
        takes ~5–8 minutes regardless of batch size, making it far more efficient than
        individual scrapes for large lists. Best combined with map_website to first
        discover URLs then scrape them all.

        Args:
            urls: Comma-separated list of URLs to scrape
                  (e.g. "https://a.com, https://b.com, https://c.com").
            formats: Comma-separated output formats: "markdown", "html", "text", "json".
                     Default: "markdown". Use "json" with parser_id for structured output.
            parser_id: Olostep parser ID to extract structured JSON from each URL
                       (e.g. "@olostep/google-search", "@olostep/extract-emails").
            country: Two-letter country code for geo-targeting all URLs (e.g. "us").

        Returns:
            JSON string — a list of objects, each with:
              "url": the scraped URL,
              "custom_id": internal hash ID,
              "content": the scraped content string.
            Returns an error message string on failure.
        """
        try:
            url_list = [u.strip() for u in urls.split(",") if u.strip()]
            if not url_list:
                return "Error: no valid URLs provided."

            fmt_list = [f.strip() for f in formats.split(",")]

            batch_kwargs: Dict[str, Any] = {"urls": url_list}

            if parser_id:
                batch_kwargs["parser"] = {"id": parser_id}
            if country:
                batch_kwargs["country"] = country.lower()

            batch = self.client.batches.create(**batch_kwargs)

            results: List[Dict[str, str]] = []
            for item in batch.items():
                try:
                    content_obj = item.retrieve(fmt_list)
                    if "json" in fmt_list and content_obj.json_content:
                        content = content_obj.json_content
                    elif "markdown" in fmt_list and content_obj.markdown_content:
                        content = content_obj.markdown_content
                    elif "text" in fmt_list and content_obj.text_content:
                        content = content_obj.text_content
                    elif "html" in fmt_list and content_obj.html_content:
                        content = content_obj.html_content
                    else:
                        content = ""
                except Exception as item_err:
                    log_error(f"Failed to retrieve batch item {item.url}: {item_err}")
                    content = ""

                results.append({
                    "url": item.url,
                    "custom_id": item.custom_id,
                    "content": content,
                })

            return json.dumps(results, ensure_ascii=False)

        except Olostep_BaseError as e:
            return f"Olostep API error in batch scrape: {type(e).__name__}: {e}"
        except Exception as e:
            return f"Unexpected error in batch scrape: {e}"
