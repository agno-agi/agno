import json
from typing import Any, Dict, List, Optional

import httpx

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info


class LLMsTxtTools(Toolkit):
    """Tools for reading llms.txt files and loading their linked documentation into a knowledge base.

    The llms.txt format (see https://llmstxt.org) is a standardized way for websites to provide
    LLM-friendly documentation indexes.

    This toolkit provides two usage modes:

    **Agentic mode (without knowledge):** The agent gets two tools:
    - `get_llms_txt_index` - reads the llms.txt and returns the index of available docs
    - `read_llms_txt_url` - fetches a specific URL from the index
    The agent reads the index, decides which pages are relevant, and fetches only those.

    **Knowledge mode (with knowledge):** The agent gets one tool:
    - `read_llms_txt_and_load_knowledge` - reads the llms.txt, fetches all linked pages,
      and loads them into the knowledge base.

    Args:
        knowledge: Optional Knowledge instance. When provided, enables knowledge loading mode.
        max_urls: Maximum number of linked URLs to fetch when loading into knowledge. Defaults to 100.
        timeout: HTTP request timeout in seconds. Defaults to 30.
        skip_optional: Whether to skip URLs listed in the "Optional" section. Defaults to False.

    Example:
        # Agentic mode - agent reads index and picks which docs to fetch
        tools = LLMsTxtTools()
        agent = Agent(tools=[tools])

        # Knowledge mode - bulk load all docs into KB
        knowledge = Knowledge(vector_db=my_vector_db)
        tools = LLMsTxtTools(knowledge=knowledge)
        agent = Agent(tools=[tools], knowledge=knowledge)
    """

    def __init__(
        self,
        knowledge: Optional[Knowledge] = None,
        max_urls: int = 100,
        timeout: int = 30,
        skip_optional: bool = False,
        **kwargs,
    ):
        from agno.knowledge.reader.llms_txt_reader import LLMsTxtReader

        self.knowledge: Optional[Knowledge] = knowledge
        self.max_urls = max_urls
        self.timeout = timeout
        self.skip_optional = skip_optional
        self.reader = LLMsTxtReader(
            max_urls=max_urls,
            timeout=timeout,
            skip_optional=skip_optional,
        )

        tools: List[Any] = []
        async_tools_list: List[tuple] = []
        if self.knowledge is not None:
            tools.append(self.read_llms_txt_and_load_knowledge)
            async_tools_list.append((self.aread_llms_txt_and_load_knowledge, "read_llms_txt_and_load_knowledge"))
        else:
            tools.append(self.get_llms_txt_index)
            tools.append(self.read_llms_txt_url)
            async_tools_list.append((self.aget_llms_txt_index, "get_llms_txt_index"))
            async_tools_list.append((self.aread_llms_txt_url, "read_llms_txt_url"))

        super().__init__(name="llms_txt_tools", tools=tools, async_tools=async_tools_list, **kwargs)

    def _async_client_kwargs(self) -> Dict[str, Any]:
        """Build kwargs for httpx.AsyncClient matching the reader's config."""
        kwargs: Dict[str, Any] = {"timeout": httpx.Timeout(self.timeout)}
        if self.reader.proxy:
            kwargs["proxy"] = self.reader.proxy
        return kwargs

    def get_llms_txt_index(self, url: str) -> str:
        """Reads an llms.txt file and returns the index of all available documentation pages.

        An llms.txt file is a standardized index of documentation for a project.
        This function reads the index and returns all available pages with their titles,
        URLs, descriptions, and sections. Use this to discover what documentation is
        available, then use read_llms_txt_url to fetch specific pages.

        :param url: The URL of the llms.txt file (e.g. https://docs.example.com/llms.txt).
        :return: JSON with the overview and list of available documentation pages.
        """
        log_info(f"Reading llms.txt index from {url}")
        llms_txt_content = self.reader.fetch_url(url)
        if not llms_txt_content:
            return f"Failed to fetch llms.txt from {url}"

        overview, entries = self.reader.parse_llms_txt(llms_txt_content, url)

        index = {
            "overview": overview,
            "pages": [
                {
                    "title": entry.title,
                    "url": entry.url,
                    "description": entry.description,
                    "section": entry.section,
                }
                for entry in entries
            ],
            "total_pages": len(entries),
        }
        return json.dumps(index)

    async def aget_llms_txt_index(self, url: str) -> str:
        """Reads an llms.txt file and returns the index of all available documentation pages.

        An llms.txt file is a standardized index of documentation for a project.
        This function reads the index and returns all available pages with their titles,
        URLs, descriptions, and sections. Use this to discover what documentation is
        available, then use read_llms_txt_url to fetch specific pages.

        :param url: The URL of the llms.txt file (e.g. https://docs.example.com/llms.txt).
        :return: JSON with the overview and list of available documentation pages.
        """
        log_info(f"Reading llms.txt index from {url}")
        async with httpx.AsyncClient(**self._async_client_kwargs()) as client:
            llms_txt_content = await self.reader.async_fetch_url(client, url)

        if not llms_txt_content:
            return f"Failed to fetch llms.txt from {url}"

        overview, entries = self.reader.parse_llms_txt(llms_txt_content, url)

        index = {
            "overview": overview,
            "pages": [
                {
                    "title": entry.title,
                    "url": entry.url,
                    "description": entry.description,
                    "section": entry.section,
                }
                for entry in entries
            ],
            "total_pages": len(entries),
        }
        return json.dumps(index)

    def read_llms_txt_url(self, url: str) -> str:
        """Fetches and returns the content of a specific documentation page URL.

        Use this after calling get_llms_txt_index to fetch the content of specific pages
        you want to read. You can call this multiple times for different URLs.

        :param url: The URL of the documentation page to read.
        :return: The text content of the page.
        """
        log_debug(f"Fetching URL: {url}")
        content = self.reader.fetch_url(url)
        if not content:
            return f"Failed to fetch content from {url}"

        return content

    async def aread_llms_txt_url(self, url: str) -> str:
        """Fetches and returns the content of a specific documentation page URL.

        Use this after calling get_llms_txt_index to fetch the content of specific pages
        you want to read. You can call this multiple times for different URLs.

        :param url: The URL of the documentation page to read.
        :return: The text content of the page.
        """
        log_debug(f"Fetching URL: {url}")
        async with httpx.AsyncClient(**self._async_client_kwargs()) as client:
            content = await self.reader.async_fetch_url(client, url)

        if not content:
            return f"Failed to fetch content from {url}"

        return content

    def read_llms_txt_and_load_knowledge(self, url: str) -> str:
        """Reads an llms.txt file, fetches all linked documentation pages, and loads them into the knowledge base.

        An llms.txt file is a standardized index of documentation for a project.
        This function reads the index, fetches every linked page, and stores the content
        in the knowledge base for future retrieval.

        :param url: The URL of the llms.txt file (e.g. https://docs.example.com/llms.txt).
        :return: Summary of what was loaded into the knowledge base.
        """
        if self.knowledge is None:
            return "Knowledge base not provided"

        log_info(f"Reading llms.txt from {url}")
        documents: List[Document] = self.reader.read(url=url)

        if not documents:
            return f"No documents found in llms.txt at {url}"

        log_debug(f"Loading {len(documents)} documents into knowledge base")
        for doc in documents:
            self.knowledge.insert(
                text_content=doc.content,
                name=doc.name,
                metadata=doc.meta_data,
            )

        return f"Successfully loaded {len(documents)} documents from llms.txt into the knowledge base"

    async def aread_llms_txt_and_load_knowledge(self, url: str) -> str:
        """Reads an llms.txt file, fetches all linked documentation pages, and loads them into the knowledge base.

        An llms.txt file is a standardized index of documentation for a project.
        This function reads the index, fetches every linked page, and stores the content
        in the knowledge base for future retrieval.

        :param url: The URL of the llms.txt file (e.g. https://docs.example.com/llms.txt).
        :return: Summary of what was loaded into the knowledge base.
        """
        if self.knowledge is None:
            return "Knowledge base not provided"

        log_info(f"Reading llms.txt from {url}")
        documents: List[Document] = await self.reader.async_read(url=url)

        if not documents:
            return f"No documents found in llms.txt at {url}"

        log_debug(f"Loading {len(documents)} documents into knowledge base")
        for doc in documents:
            await self.knowledge.ainsert(
                text_content=doc.content,
                name=doc.name,
                metadata=doc.meta_data,
            )

        return f"Successfully loaded {len(documents)} documents from llms.txt into the knowledge base"
