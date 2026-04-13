import json
from typing import Callable, List, Optional

import httpx

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.llms_txt_reader import LLMsTxtReader
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info


class LLMsTxtTools(Toolkit):
    def __init__(
        self,
        knowledge: Optional[Knowledge] = None,
        max_urls: int = 20,
        timeout: int = 60,
        skip_optional: bool = False,
        **kwargs,
    ):
        self.knowledge: Optional[Knowledge] = knowledge
        self.max_urls = max_urls
        self.timeout = timeout
        self.skip_optional = skip_optional
        self.reader = LLMsTxtReader(
            max_urls=max_urls,
            timeout=timeout,
            skip_optional=skip_optional,
        )

        tools: List[Callable] = []
        async_tools_list: List[tuple] = []
        # Agentic mode — agent picks which pages to read
        if self.knowledge is None:
            tools.append(self.get_llms_txt_index)
            tools.append(self.read_llms_txt_url)
            async_tools_list.append((self.aget_llms_txt_index, "get_llms_txt_index"))
            async_tools_list.append((self.aread_llms_txt_url, "read_llms_txt_url"))
        # Knowledge mode — bulk load all pages into vector DB
        else:
            tools.append(self.read_llms_txt_and_load_knowledge)
            async_tools_list.append((self.aread_llms_txt_and_load_knowledge, "read_llms_txt_and_load_knowledge"))

        super().__init__(name="llms_txt_tools", tools=tools, async_tools=async_tools_list, **kwargs)

    # Helpers

    def _async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, proxy=self.reader.proxy)

    def _format_index(self, overview: str, entries: list) -> str:
        return json.dumps(
            {
                "overview": overview,
                "pages": [
                    {"title": e.title, "url": e.url, "description": e.description, "section": e.section}
                    for e in entries
                ],
                "total_pages": len(entries),
            }
        )

    # Tools

    def get_llms_txt_index(self, url: str) -> str:
        """
        Reads an llms.txt file and returns the index of all available documentation pages.
        Use this to discover what pages are available, then use read_llms_txt_url to fetch specific pages.

        Args:
            url (str): The URL of the llms.txt file (e.g. https://docs.example.com/llms.txt)

        Returns:
            str: JSON with the overview and list of available documentation pages
        """
        try:
            log_info(f"Reading llms.txt index from {url}")
            llms_txt_content = self.reader.fetch_url(url)
            if not llms_txt_content:
                return f"Failed to fetch llms.txt from {url}"

            overview, entries = self.reader.parse_llms_txt(llms_txt_content, url)
            return self._format_index(overview, entries)
        except Exception as e:
            return f"Error reading llms.txt index from {url}: {type(e).__name__}: {e}"

    async def aget_llms_txt_index(self, url: str) -> str:
        """
        Reads an llms.txt file and returns the index of all available documentation pages.
        Use this to discover what pages are available, then use read_llms_txt_url to fetch specific pages.

        Args:
            url (str): The URL of the llms.txt file (e.g. https://docs.example.com/llms.txt)

        Returns:
            str: JSON with the overview and list of available documentation pages
        """
        try:
            log_info(f"Reading llms.txt index from {url}")
            async with self._async_client() as client:
                llms_txt_content = await self.reader.async_fetch_url(client, url)

            if not llms_txt_content:
                return f"Failed to fetch llms.txt from {url}"

            overview, entries = self.reader.parse_llms_txt(llms_txt_content, url)
            return self._format_index(overview, entries)
        except Exception as e:
            return f"Error reading llms.txt index from {url}: {type(e).__name__}: {e}"

    def read_llms_txt_url(self, url: str) -> str:
        """
        Fetches and returns the content of a specific documentation page.
        Use this after calling get_llms_txt_index to read pages relevant to the user's question.

        Args:
            url (str): The URL of the documentation page to read

        Returns:
            str: The text content of the page
        """
        try:
            log_debug(f"Fetching URL: {url}")
            content = self.reader.fetch_url(url)
            if not content:
                return f"Failed to fetch content from {url}"
            return content
        except Exception as e:
            return f"Error fetching {url}: {type(e).__name__}: {e}"

    async def aread_llms_txt_url(self, url: str) -> str:
        """
        Fetches and returns the content of a specific documentation page.
        Use this after calling get_llms_txt_index to read pages relevant to the user's question.

        Args:
            url (str): The URL of the documentation page to read

        Returns:
            str: The text content of the page
        """
        try:
            log_debug(f"Fetching URL: {url}")
            async with self._async_client() as client:
                content = await self.reader.async_fetch_url(client, url)

            if not content:
                return f"Failed to fetch content from {url}"
            return content
        except Exception as e:
            return f"Error fetching {url}: {type(e).__name__}: {e}"

    def read_llms_txt_and_load_knowledge(self, url: str) -> str:
        """
        Reads an llms.txt file, fetches all linked pages, and loads them into the knowledge base.

        Args:
            url (str): The URL of the llms.txt file (e.g. https://docs.example.com/llms.txt)

        Returns:
            str: Summary of what was loaded into the knowledge base
        """
        if self.knowledge is None:
            return "Knowledge base not provided"

        try:
            log_info(f"Reading llms.txt from {url}")
            self.knowledge.insert(url=url, reader=self.reader)
            return f"Successfully loaded documentation from {url} into the knowledge base"
        except Exception as e:
            return f"Error loading knowledge from {url}: {type(e).__name__}: {e}"

    async def aread_llms_txt_and_load_knowledge(self, url: str) -> str:
        """
        Reads an llms.txt file, fetches all linked pages, and loads them into the knowledge base.

        Args:
            url (str): The URL of the llms.txt file (e.g. https://docs.example.com/llms.txt)

        Returns:
            str: Summary of what was loaded into the knowledge base
        """
        if self.knowledge is None:
            return "Knowledge base not provided"

        try:
            log_info(f"Reading llms.txt from {url}")
            await self.knowledge.ainsert(url=url, reader=self.reader)
            return f"Successfully loaded documentation from {url} into the knowledge base"
        except Exception as e:
            return f"Error loading knowledge from {url}: {type(e).__name__}: {e}"
