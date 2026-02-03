import json
from typing import Any, Callable, List, Optional

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.wikipedia_reader import WikipediaReader
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

try:
    import wikipedia
    from wikipedia.exceptions import DisambiguationError, PageError
except ImportError:
    logger.error("Wikipedia tools require the `wikipedia` package. Please install it using `pip install wikipedia`.")


class WikipediaTools(Toolkit):
    def __init__(
        self,
        knowledge: Optional[Knowledge] = None,
        language: str = "en",
        max_search_results: int = 5,
        auto_suggest: bool = True,
        enable_search: bool = True,
        enable_get_page: bool = True,
        enable_get_summary: bool = True,
        enable_search_and_update_kb: bool = True,
        enable_get_page_sections: bool = True,
        enable_get_related_pages: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize WikipediaTools.

        Args:
            knowledge: Optional Knowledge base for storing Wikipedia content
            language: Wikipedia language code (default: "en")
            max_search_results: Maximum number of search results to return (default: 5)
            auto_suggest: Enable automatic suggestion for ambiguous queries (default: True)
            enable_search: Enable the search_wikipedia tool
            enable_get_page: Enable the get_wikipedia_page tool
            enable_get_summary: Enable the get_wikipedia_summary tool
            enable_search_and_update_kb: Enable the search_wikipedia_and_update_knowledge_base tool
            enable_get_page_sections: Enable the get_page_sections tool
            enable_get_related_pages: Enable the get_related_pages tool
            all: Enable all tools (overrides individual enable flags)
            **kwargs: Additional arguments passed to Toolkit
        """
        self.knowledge: Optional[Knowledge] = knowledge
        self.language: str = language
        self.max_search_results: int = max_search_results
        self.auto_suggest: bool = auto_suggest

        # Set Wikipedia language
        try:
            wikipedia.set_lang(self.language)
        except Exception as e:
            logger.warning(f"Failed to set Wikipedia language to {self.language}: {e}")

        tools: List[Callable[..., Any]] = []

        # Add tools based on configuration
        if all or enable_search:
            tools.append(self.search_wikipedia)

        if all or enable_get_page:
            tools.append(self.get_wikipedia_page)

        if all or enable_get_summary:
            tools.append(self.get_wikipedia_summary)

        if (all or enable_search_and_update_kb) and self.knowledge is not None:
            tools.append(self.search_wikipedia_and_update_knowledge_base)

        if all or enable_get_page_sections:
            tools.append(self.get_page_sections)

        if all or enable_get_related_pages:
            tools.append(self.get_related_pages)

        super().__init__(name="wikipedia_tools", tools=tools, **kwargs)

    def search_wikipedia_and_update_knowledge_base(self, topic: str) -> str:
        """This function searches wikipedia for a topic, adds the results to the knowledge base and returns them.

        USE THIS FUNCTION TO GET INFORMATION WHICH DOES NOT EXIST.

        :param topic: The topic to search Wikipedia and add to knowledge base.
        :return: Relevant documents from Wikipedia knowledge base.
        """

        if self.knowledge is None:
            return "Knowledge not provided"

        log_debug(f"Adding to knowledge: {topic}")
        self.knowledge.insert(
            topics=[topic],
            reader=WikipediaReader(),
        )
        log_debug(f"Searching knowledge: {topic}")
        relevant_docs: List[Document] = self.knowledge.search(query=topic)
        return json.dumps([doc.to_dict() for doc in relevant_docs])

    def search_wikipedia(self, query: str, max_results: Optional[int] = None) -> str:
        """Searches Wikipedia for a query and returns multiple search results.

        :param query: The query to search for.
        :param max_results: Maximum number of results to return (defaults to toolkit's max_search_results).
        :return: JSON formatted list of search results with titles and summaries.
        """
        try:
            results_limit = max_results or self.max_search_results
            log_info(f"Searching Wikipedia for: {query} (max results: {results_limit})")

            # Get search results
            search_results = wikipedia.search(query, results=results_limit)

            if not search_results:
                return json.dumps({"query": query, "results": [], "message": "No results found for the given query."})

            # Get summaries for each result
            detailed_results = []
            for title in search_results[:results_limit]:
                try:
                    summary = wikipedia.summary(title, sentences=3, auto_suggest=self.auto_suggest)
                    detailed_results.append(
                        {
                            "title": title,
                            "summary": summary,
                            "url": f"https://{self.language}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                        }
                    )
                except DisambiguationError as e:
                    detailed_results.append(
                        {
                            "title": title,
                            "summary": "Disambiguation page - multiple meanings exist",
                            "options": e.options[:5],
                            "url": f"https://{self.language}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                        }
                    )
                except PageError:
                    log_debug(f"Page not found for title: {title}")
                    continue
                except Exception as e:
                    log_debug(f"Error getting summary for {title}: {e}")
                    continue

            return json.dumps(
                {"query": query, "results_count": len(detailed_results), "results": detailed_results}, indent=2
            )

        except Exception as e:
            logger.error(f"Error searching Wikipedia: {e}")
            return json.dumps(
                {"query": query, "error": str(e), "message": "An error occurred while searching Wikipedia."}
            )

    def get_wikipedia_page(self, title: str, include_full_content: bool = False) -> str:
        """Gets detailed information about a specific Wikipedia page.

        :param title: The title of the Wikipedia page.
        :param include_full_content: Whether to include full page content (default: False for performance).
        :return: JSON formatted page information including summary, URL, and optionally full content.
        """
        try:
            log_info(f"Getting Wikipedia page: {title}")

            page = wikipedia.page(title, auto_suggest=self.auto_suggest)

            result = {
                "title": page.title,
                "url": page.url,
                "summary": page.summary,
                "categories": page.categories if hasattr(page, "categories") else [],
                "links": page.links[:20] if hasattr(page, "links") else [],  # Limit to first 20 links
            }

            if include_full_content:
                result["content"] = page.content

            return json.dumps(result, indent=2)

        except DisambiguationError as e:
            return json.dumps(
                {
                    "title": title,
                    "error": "DisambiguationError",
                    "message": f"'{title}' may refer to multiple pages. Please be more specific.",
                    "options": e.options[:10],
                },
                indent=2,
            )
        except PageError:
            return json.dumps(
                {"title": title, "error": "PageError", "message": f"Page '{title}' does not exist on Wikipedia."},
                indent=2,
            )
        except Exception as e:
            logger.error(f"Error getting Wikipedia page: {e}")
            return json.dumps(
                {"title": title, "error": str(e), "message": "An error occurred while fetching the Wikipedia page."},
                indent=2,
            )

    def get_wikipedia_summary(self, title: str, sentences: int = 5) -> str:
        """Gets a summary of a Wikipedia page.

        :param title: The title of the Wikipedia page.
        :param sentences: Number of sentences in the summary (default: 5).
        :return: JSON formatted summary of the page.
        """
        try:
            log_info(f"Getting Wikipedia summary for: {title} ({sentences} sentences)")

            summary = wikipedia.summary(title, sentences=sentences, auto_suggest=self.auto_suggest)
            page = wikipedia.page(title, auto_suggest=self.auto_suggest)

            return json.dumps(
                {"title": page.title, "summary": summary, "url": page.url, "sentences": sentences}, indent=2
            )

        except DisambiguationError as e:
            return json.dumps(
                {
                    "title": title,
                    "error": "DisambiguationError",
                    "message": f"'{title}' may refer to multiple pages.",
                    "options": e.options[:10],
                },
                indent=2,
            )
        except PageError:
            return json.dumps(
                {"title": title, "error": "PageError", "message": f"Page '{title}' does not exist."}, indent=2
            )
        except Exception as e:
            logger.error(f"Error getting Wikipedia summary: {e}")
            return json.dumps(
                {"title": title, "error": str(e), "message": "An error occurred while fetching the summary."}, indent=2
            )

    def get_page_sections(self, title: str) -> str:
        """Gets the section structure of a Wikipedia page.

        :param title: The title of the Wikipedia page.
        :return: JSON formatted list of sections in the page.
        """
        try:
            log_info(f"Getting sections for Wikipedia page: {title}")

            page = wikipedia.page(title, auto_suggest=self.auto_suggest)

            # Parse sections from content
            sections = []
            content_lines = page.content.split("\n")

            for i, line in enumerate(content_lines):
                if line.startswith("==") and line.endswith("=="):
                    # Count the level of the section
                    level = (len(line) - len(line.lstrip("="))) // 2
                    section_title = line.strip("= ")
                    sections.append({"title": section_title, "level": level, "position": i})

            return json.dumps(
                {"page_title": page.title, "url": page.url, "sections_count": len(sections), "sections": sections},
                indent=2,
            )

        except DisambiguationError as e:
            return json.dumps({"title": title, "error": "DisambiguationError", "options": e.options[:10]}, indent=2)
        except PageError:
            return json.dumps(
                {"title": title, "error": "PageError", "message": f"Page '{title}' does not exist."}, indent=2
            )
        except Exception as e:
            logger.error(f"Error getting page sections: {e}")
            return json.dumps({"title": title, "error": str(e)}, indent=2)

    def get_related_pages(self, title: str, max_links: int = 10) -> str:
        """Gets related Wikipedia pages based on links from the specified page.

        :param title: The title of the Wikipedia page.
        :param max_links: Maximum number of related links to return (default: 10).
        :return: JSON formatted list of related page titles.
        """
        try:
            log_info(f"Getting related pages for: {title}")

            page = wikipedia.page(title, auto_suggest=self.auto_suggest)

            # Get links from the page
            related_links = page.links[:max_links] if hasattr(page, "links") else []

            return json.dumps(
                {
                    "page_title": page.title,
                    "url": page.url,
                    "related_count": len(related_links),
                    "related_pages": related_links,
                    "message": f"Found {len(related_links)} related pages",
                },
                indent=2,
            )

        except DisambiguationError as e:
            return json.dumps({"title": title, "error": "DisambiguationError", "options": e.options[:10]}, indent=2)
        except PageError:
            return json.dumps(
                {"title": title, "error": "PageError", "message": f"Page '{title}' does not exist."}, indent=2
            )
        except Exception as e:
            logger.error(f"Error getting related pages: {e}")
            return json.dumps({"title": title, "error": str(e)}, indent=2)
