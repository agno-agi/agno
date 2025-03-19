import json
from typing import List, Optional, cast

from agno.document import Document
from agno.knowledge.combined import CombinedKnowledgeBase
from agno.knowledge.website import WebsiteKnowledgeBase
from agno.tools import Toolkit
from agno.utils.log import logger


class WebsiteTools(Toolkit):
    def __init__(self, knowledge_base: Optional[WebsiteKnowledgeBase | CombinedKnowledgeBase] = None):
        super().__init__(name="website_tools")
        self.knowledge_base: Optional[WebsiteKnowledgeBase | CombinedKnowledgeBase] = knowledge_base

        if self.knowledge_base is not None:
            if isinstance(self.knowledge_base, WebsiteKnowledgeBase):
                self.register(self.add_website_to_knowledge_base)
            elif isinstance(self.knowledge_base, CombinedKnowledgeBase):
                self.register(self.add_website_to_combined_knowledge_base)
        else:
            self.register(self.read_url)

    def add_website_to_knowledge_base(self, url: str) -> str:
        """This function adds a websites content to the knowledge base.
        NOTE: The website must start with https:// and should be a valid website.

        USE THIS FUNCTION TO GET INFORMATION ABOUT PRODUCTS FROM THE INTERNET.

        :param url: The url of the website to add.
        :return: 'Success' if the website was added to the knowledge base.
        """
        self.knowledge_base = cast(WebsiteKnowledgeBase, self.knowledge_base)
        if self.knowledge_base is None:
            return "Knowledge base not provided"

        logger.debug(f"Adding to knowledge base: {url}")
        self.knowledge_base.urls.append(url)
        logger.debug("Loading knowledge base.")
        self.knowledge_base.load(recreate=False)
        return "Success"

    def add_website_to_combined_knowledge_base(self, url: str) -> str:
        """This function adds a websites content to the knowledge base.
        NOTE: The website must start with https:// and should be a valid website.

        USE THIS FUNCTION TO GET INFORMATION ABOUT PRODUCTS FROM THE INTERNET.

        :param url: The url of the website to add.
        :return: 'Success' if the website was added to the knowledge base.
        """
        self.knowledge_base = cast(CombinedKnowledgeBase, self.knowledge_base)
        if self.knowledge_base is None:
            return "Knowledge base not provided"

        website_knowledge_base = None
        for knowledge_base in self.knowledge_base.sources:
            if isinstance(knowledge_base, WebsiteKnowledgeBase):
                website_knowledge_base = knowledge_base
                break

        if website_knowledge_base is None:
            return "Website knowledge base not found"

        logger.debug(f"Adding to knowledge base: {url}")
        website_knowledge_base.urls.append(url)
        logger.debug("Loading knowledge base.")
        website_knowledge_base.load(recreate=False)
        return "Success"

    def read_url(self, url: str) -> str:
        """This function reads a url and returns the content.

        :param url: The url of the website to read.
        :return: Relevant documents from the website.
        """
        from agno.document.reader.website_reader import WebsiteReader

        website = WebsiteReader()

        logger.debug(f"Reading website: {url}")
        relevant_docs: List[Document] = website.read(url=url)
        return json.dumps([doc.to_dict() for doc in relevant_docs])
