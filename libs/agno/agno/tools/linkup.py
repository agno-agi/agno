import json
from os import getenv
from typing import Callable, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from linkup import LinkupClient
except ImportError:
    raise ImportError("`linkup-sdk` not installed. Please install using `pip install linkup-sdk`")


class LinkupTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        depth: Literal["fast", "standard", "deep"] = "standard",
        output_type: Literal["searchResults", "sourcedAnswer", "structured"] = "searchResults",
        web_search_with_linkup: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("LINKUP_API_KEY")
        if not self.api_key:
            log_error("LINKUP_API_KEY not set. Please set the LINKUP_API_KEY environment variable.")

        self.linkup = LinkupClient(api_key=self.api_key)
        self.depth = depth
        self.output_type = output_type

        tools: List[Callable] = []
        if all or web_search_with_linkup:
            tools.append(self.web_search_with_linkup)

        super().__init__(name="linkup_tools", tools=tools, **kwargs)

    def web_search_with_linkup(self, query: str, depth: Optional[str] = None, output_type: Optional[str] = None) -> str:
        """Search the web using Linkup API.

        Args:
            query: Query to search for.
            depth: Search depth (standard, deep, or fast). Defaults to toolkit setting.
            output_type: Output format (searchResults or sourcedAnswer). Defaults to toolkit setting.

        Returns:
            Search results from Linkup.
        """
        try:
            response = self.linkup.search(
                query=query,
                depth=depth or self.depth,  # type: ignore
                output_type=output_type or self.output_type,  # type: ignore
            )
            if isinstance(response, str):
                return response
            if hasattr(response, "model_dump"):
                return json.dumps(response.model_dump(), default=str)
            return json.dumps(response, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})
