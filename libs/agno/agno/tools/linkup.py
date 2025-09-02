from os import getenv
from typing import Any, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from linkup import LinkupClient
except ImportError:
    raise ImportError("`linkup-sdk` not installed. Please install using `pip install linkup-sdk`")


class LinkupTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        depth: Literal["standard", "deep"] = "standard",
        output_type: Literal["sourcedAnswer", "searchResults"] = "searchResults",
        **kwargs,
    ):
        self.api_key = api_key or getenv("LINKUP_API_KEY")
        if not self.api_key:
            logger.error("LINKUP_API_KEY not set. Please set the LINKUP_API_KEY environment variable.")

        self.linkup = LinkupClient(api_key=api_key)
        self.depth = depth
        self.output_type = output_type

        tools: List[Any] = [self.web_search_with_linkup]

        super().__init__(name="linkup_tools", tools=tools, **kwargs)

    def web_search_with_linkup(self, query: str, depth: Optional[str] = None, output_type: Optional[str] = None) -> str:
        """
        Use this function to search the web for a given query.
        This function uses the Linkup API to provide realtime online information about the query.

        Args:
            query (str): Query to search for.
            depth (str): (deep|standard) Depth of the search. Defaults to 'standard'.
            output_type (str): (sourcedAnswer|searchResults) Type of output. Defaults to 'searchResults'.

        Returns:
            str: string of results related to the query.
        """
        try:
            response = self.linkup.search(
                query=query,
                depth=depth or self.depth,  # type: ignore
                output_type=output_type or self.output_type,  # type: ignore
            )
            return response
        except Exception as e:
            return f"Error: {str(e)}"
