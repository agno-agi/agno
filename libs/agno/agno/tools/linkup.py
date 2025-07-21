
from agno.tools import Toolkit
from typing import Any, List, Optional
from os import getenv
from agno.utils.log import logger

try:
    from linkup import LinkupClient
    LINKUP_AVAILABLE = True
except ImportError as e:
    LINKUP_AVAILABLE = False
    LinkupClient = Any

class LinkupTools(Toolkit):
    def __init__(
        self,
        search: bool = True,
        answer: bool = True,
        research: bool = False,
        api_key: Optional[str] = None,
        get_content: bool = False,
        depth: str = "standard",
        output_type: str = "searchResults",
        **kwargs
    ):
        self.api_key = api_key or getenv("LINKUP_API_KEY")
        if not self.api_key:
            logger.error("LINKUP_API_KEY not set. Please set the LINKUP_API_KEY environment variable.")

        if not LINKUP_AVAILABLE:
            import click

            if click.confirm(
                "You are missing the 'linkup-sdk' package. Would you like to install it?"
            ):
                import subprocess

                try:
                    subprocess.run(["uv", "add", "linkup-sdk"], check=True)
                except subprocess.CalledProcessError:
                    raise ImportError("Failed to install 'linkup-sdk' package")

        from linkup import LinkupClient

        self.linkup = LinkupClient(api_key=api_key)
        self.depth = depth
        self.output_type = output_type

        tools: List[Any] = []
        if search:
            tools.append(self.web_search_with_linkup)
        if research:
            tools.append(self.web_search_with_linkup)
        if get_content:
            tools.append(self.web_search_with_linkup)
        if answer:
            tools.append(self.web_search_with_linkup)

        super().__init__(name="linkup_tools", tools=tools, **kwargs)

    def web_search_with_linkup(self, query:str,  depth: str = 'standard', output_type: str='searchResults') -> str:
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
            response = self.linkup.search(query=query, depth=depth, output_type=output_type)
            return response
        except Exception as e:
            return {"status": "error", "message": str(e)}
