import json
from typing import Any, List, Optional

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.tools import Toolkit
from agno.utils.log import log_debug


class WebsiteTools(Toolkit):
    def __init__(
        self,
        knowledge: Optional[Knowledge] = None,
        **kwargs,
    ):
        self.knowledge: Optional[Knowledge] = knowledge

        tools: List[Any] = []
        if self.knowledge is not None:
            tools.append(self.add_website_to_knowledge)
        else:
            tools.append(self.read_url)

        super().__init__(name="website_tools", tools=tools, **kwargs)

    def add_website_to_knowledge(self, url: str) -> str:
        """This function adds a websites content to the knowledge base.
        NOTE: The website must start with https:// and should be a valid website.

        USE THIS FUNCTION TO GET INFORMATION ABOUT PRODUCTS FROM THE INTERNET.

        :param url: The url of the website to add.
        :return: 'Success' if the website was added to the knowledge base.
        """
        if self.knowledge is None:
            return "Knowledge base not provided"

        log_debug(f"Adding to knowledge base: {url}")
        self.knowledge.add_content(url=url)
        return "Success"

    def read_url(self, url: str) -> str:
        """This function reads a url and returns the content.

        :param url: The url of the website to read.
        :return: Relevant documents from the website.
        """
        from agno.knowledge.reader.website_reader import WebsiteReader

        website = WebsiteReader()

        log_debug(f"Reading website: {url}")
        relevant_docs: List[Document] = website.read(url=url)
        return json.dumps([doc.to_dict() for doc in relevant_docs])
