import json
from typing import Any, List, Optional

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.tools import Toolkit
from agno.tools._security import validate_public_url
from agno.utils.log import log_debug, log_warning


class WebsiteTools(Toolkit):
    """Website / URL-reading toolkit.

    Security notes (hardened build):

    * Every URL is validated by
      :func:`agno.tools._security.validate_public_url` before a
      request is issued. The scheme must be ``http`` / ``https`` and
      every resolved A/AAAA address must be a public unicast address
      unless ``allow_private_networks=True``.

    Args:
        knowledge: Optional knowledge base. When provided,
            :meth:`add_website_to_knowledge` is registered in place
            of :meth:`read_url`.
        allow_private_networks: Skip the SSRF address-class check.
            Use only when reading intranet or VPC-internal URLs.
    """

    def __init__(
        self,
        knowledge: Optional[Knowledge] = None,
        allow_private_networks: bool = False,
        **kwargs,
    ):
        self.knowledge: Optional[Knowledge] = knowledge
        self._allow_private_networks = bool(allow_private_networks)

        tools: List[Any] = []
        if self.knowledge is not None:
            tools.append(self.add_website_to_knowledge)
        else:
            tools.append(self.read_url)

        super().__init__(name="website_tools", tools=tools, **kwargs)

    def _validate(self, url: str) -> Optional[str]:
        """Return a reason string if ``url`` is rejected, else None."""
        try:
            validate_public_url(
                url,
                allow_private_networks=self._allow_private_networks,
            )
            return None
        except ValueError as e:
            log_warning(f"WebsiteTools blocked URL: {e}")
            return str(e)

    def add_website_to_knowledge(self, url: str) -> str:
        """This function adds a websites content to the knowledge base.
        NOTE: The website must start with https:// and should be a valid website.

        USE THIS FUNCTION TO GET INFORMATION ABOUT PRODUCTS FROM THE INTERNET.

        :param url: The url of the website to add.
        :return: 'Success' if the website was added to the knowledge base.
        """
        if self.knowledge is None:
            return "Knowledge base not provided"
        err = self._validate(url)
        if err:
            return f"Error: {err}"

        log_debug(f"Adding to knowledge base: {url}")
        self.knowledge.insert(url=url)
        return "Success"

    def read_url(self, url: str) -> str:
        """This function reads a url and returns the content.

        :param url: The url of the website to read.
        :return: Relevant documents from the website.
        """
        from agno.knowledge.reader.website_reader import WebsiteReader

        err = self._validate(url)
        if err:
            return json.dumps({"error": err})

        website = WebsiteReader()

        log_debug(f"Reading website: {url}")
        relevant_docs: List[Document] = website.read(url=url)
        return json.dumps([doc.to_dict() for doc in relevant_docs])
