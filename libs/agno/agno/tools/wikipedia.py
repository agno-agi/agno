import json
from typing import List, Optional

from agno.document import Document
from agno.knowledge.wikipedia import WikipediaKnowledgeBase
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info


class WikipediaTools(Toolkit):
    def __init__(self, knowledge_base: Optional[WikipediaKnowledgeBase] = None, **kwargs):
        tools = []

        self.knowledge_base: Optional[WikipediaKnowledgeBase] = knowledge_base
        if self.knowledge_base is not None and isinstance(self.knowledge_base, WikipediaKnowledgeBase):
            tools.append(self.search_wikipedia_and_update_knowledge_base)
        else:
            tools.append(self.search_wikipedia)  # type: ignore

        super().__init__(name="wikipedia_tools", tools=tools, **kwargs)

    def search_wikipedia_and_update_knowledge_base(self, topic: str) -> str:
        """This function searches wikipedia for a topic, adds the results to the knowledge base and returns them.

        USE THIS FUNCTION TO GET INFORMATION WHICH DOES NOT EXIST.

        :param topic: The topic to search Wikipedia and add to knowledge base.
        :return: Relevant documents from Wikipedia knowledge base.
        """

        if self.knowledge_base is None:
            return "Knowledge base not provided"

        log_debug(f"Adding to knowledge base: {topic}")
        self.knowledge_base.topics.append(topic)
        log_debug("Loading knowledge base.")
        self.knowledge_base.load(recreate=False)
        log_debug(f"Searching knowledge base: {topic}")
        relevant_docs: List[Document] = self.knowledge_base.search(query=topic)
        return json.dumps([doc.to_dict() for doc in relevant_docs])

    def search_wikipedia(self, query: str) -> str:
        """Searches Wikipedia for a query.

        :param query: The query to search for.
        :return: Relevant documents from wikipedia.
        """
        try:
            import wikipedia  # noqa: F401
        except ImportError:
            raise ImportError(
                "The `wikipedia` package is not installed. Please install it via `pip install wikipedia`."
            )

        log_info(f"Searching wikipedia for: {query}")
        return json.dumps(Document(name=query, content=wikipedia.summary(query)).to_dict())
