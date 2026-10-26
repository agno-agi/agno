import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

UnbrowseRender = Literal["auto", "always", "never"]


class UnbrowseTools(Toolkit):
    """
    UnbrowseTools reads websites and calls website APIs through Unbrowse (https://unbrowse.ai).

    Unbrowse turns websites into APIs that agents can call. This toolkit talks to its hosted MCP
    endpoint over plain JSON-RPC HTTP (one POST per tool call), so no MCP client or extra dependency
    is needed. Get an API key at https://unbrowse.ai/app. Source: https://github.com/unbrowse-ai/unbrowse

    Args:
        api_key (Optional[str]): Unbrowse API key. If not provided, uses the UNBROWSE_API_KEY env var.
        base_url (str): The Unbrowse MCP endpoint. Default is "https://unbrowse.ai/api/mcp".
        timeout (float): Request timeout in seconds. Default is 120.
        render (Optional[str]): How scrape_page fetches a page: "auto" (HTTP first, cloud browser if the
            page needs it), "always" or "never" (plain HTTP only). If None, the service default ("auto") applies.
        enable_scrape_page (bool): Enable reading a page as markdown. Default is True.
        enable_discover (bool): Enable searching learned site APIs for a task. Default is True.
        enable_run_task (bool): Enable running a task or a learned site API. Default is True.
        enable_map_site (bool): Enable listing a site's URLs. Default is False.
        all (bool): If True, enable every tool regardless of the individual flags.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://unbrowse.ai/api/mcp",
        timeout: float = 120.0,
        render: Optional[UnbrowseRender] = None,
        enable_scrape_page: bool = True,
        enable_discover: bool = True,
        enable_run_task: bool = True,
        enable_map_site: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("UNBROWSE_API_KEY")
        if not self.api_key:
            log_warning("No Unbrowse API key provided. Set the UNBROWSE_API_KEY environment variable.")

        self.base_url = base_url
        self.timeout = timeout
        self.render = render

        tools: List[Any] = []
        if all or enable_scrape_page:
            tools.append(self.scrape_page)
        if all or enable_discover:
            tools.append(self.discover)
        if all or enable_run_task:
            tools.append(self.run_task)
        if all or enable_map_site:
            tools.append(self.map_site)

        super().__init__(name="unbrowse_tools", tools=tools, **kwargs)

    def _call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """
        Calls one Unbrowse MCP tool with a JSON-RPC `tools/call` request.

        Args:
            name (str): The Unbrowse tool name, e.g. "unbrowse.scrape".
            arguments (Dict[str, Any]): The tool arguments.

        Returns:
            str: The tool's text result (a JSON string), or a JSON error object.
        """
        if not self.api_key:
            return json.dumps({"error": "No Unbrowse API key provided. Set the UNBROWSE_API_KEY environment variable."})

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "agno",
        }

        try:
            log_debug(f"Calling Unbrowse tool {name}")
            response = httpx.post(self.base_url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            log_error(f"Unbrowse HTTP error: {e}")
            return json.dumps({"error": f"HTTP error {e.response.status_code}: {e.response.text[:500]}"})
        except httpx.HTTPError as e:
            log_error(f"Unbrowse request error: {e}")
            return json.dumps({"error": str(e)})
        except ValueError as e:
            log_error(f"Unbrowse JSON decode error: {e}")
            return json.dumps({"error": f"Invalid JSON response: {e}"})

        if not isinstance(data, dict):
            return json.dumps({"error": "Unexpected response from Unbrowse"})

        if data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            log_error(f"Unbrowse tool {name} failed: {message}")
            return json.dumps({"error": message})

        content = (data.get("result") or {}).get("content") or []
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        if not texts:
            return json.dumps({"error": "Unbrowse returned no content"})
        # A failed run (e.g. no_capability) comes back as a normal result with isError set.
        # Its text explains what happened and what to do next, so it is passed through as is.
        return "\n".join(texts)

    def scrape_page(self, url: str) -> str:
        """
        Read one web page as clean markdown, with its title, metadata and links.

        Use this to read a page you already have a URL for.

        Args:
            url (str): The page URL, e.g. https://docs.agno.com/introduction

        Returns:
            str: JSON string with `markdown`, `metadata` (title, language, status) and the page URL.
        """
        if not url:
            return json.dumps({"error": "Please provide a URL to scrape"})

        arguments: Dict[str, Any] = {"url": url, "formats": ["markdown"]}
        if self.render:
            arguments["render"] = self.render
        return self._call_tool("unbrowse.scrape", arguments)

    def discover(self, query: str) -> str:
        """
        Search for learned website APIs (capabilities) that can do a task, e.g. "search Hacker News".

        Each result has an `id` that can be passed to run_task as `capability`, and a description of its inputs.

        Args:
            query (str): What you want to do, in natural language.

        Returns:
            str: JSON string listing matching capabilities with their id, site, title and description.
        """
        if not query:
            return json.dumps({"error": "Please provide a query"})

        return self._call_tool("unbrowse.discover", {"query": query})

    def run_task(
        self,
        task: Optional[str] = None,
        capability: Optional[str] = None,
        input: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Run a website task through Unbrowse, either by natural-language task or by a capability id from discover.

        The result has a `status`: "succeeded" with the data in `result`; "input_required" with the missing
        inputs listed in `requirements` (call again with them in `input`); or "failed" with
        `phase` "no_capability" when no learned API fits the task yet.

        Args:
            task (Optional[str]): The task in natural language, e.g. "top stories on Hacker News".
            capability (Optional[str]): A capability id returned by discover. Takes precedence over task.
            input (Optional[Dict[str, Any]]): Inputs for the capability, keyed by the names discover lists.

        Returns:
            str: JSON string describing the run: status, result, requirements and error.
        """
        if not task and not capability:
            return json.dumps({"error": "Please provide a task or a capability id"})

        arguments: Dict[str, Any] = {}
        if capability:
            arguments["capability"] = capability
        else:
            arguments["task"] = task
        if input:
            arguments["input"] = input
        return self._call_tool("unbrowse.run", arguments)

    def map_site(self, url: str) -> str:
        """
        List a website's URLs from its sitemaps and the links on the given page (same site only).

        Use this to find the right page on a site before scraping it.

        Args:
            url (str): Any page on the site, e.g. https://docs.agno.com

        Returns:
            str: JSON string with the list of `urls` found.
        """
        if not url:
            return json.dumps({"error": "Please provide a URL to map"})

        return self._call_tool("unbrowse.map", {"url": url})
