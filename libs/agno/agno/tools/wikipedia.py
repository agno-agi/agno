import json
from typing import List, Optional

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.wikipedia_reader import WikipediaReader
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info

try:
    import wikipedia
    from wikipedia.exceptions import DisambiguationError
except ImportError:
    raise ImportError("The `wikipedia` package is not installed. Please install it via `pip install wikipedia`.")


class WikipediaTools(Toolkit):
    def __init__(
        self,
        knowledge: Optional[Knowledge] = None,
        auto_suggest: bool = True,
        all: bool = False,
        **kwargs,
    ):
        tools = []

        self.auto_suggest = auto_suggest
        self.knowledge: Optional[Knowledge] = knowledge
        if self.knowledge is not None and isinstance(self.knowledge, Knowledge):
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

        if self.knowledge is None:
            return "Knowledge not provided"

        log_debug(f"Adding to knowledge: {topic}")
        self.knowledge.insert(
            topics=[topic],
            reader=WikipediaReader(auto_suggest=self.auto_suggest),
        )
        log_debug(f"Searching knowledge: {topic}")
        relevant_docs: List[Document] = self.knowledge.search(query=topic)
        return json.dumps([doc.to_dict() for doc in relevant_docs])

    def search_wikipedia(self, query: str) -> str:
        """Searches Wikipedia for a query.

        :param query: The query to search for.
        :return: Relevant documents from wikipedia.
        """
        log_info(f"Searching wikipedia for: {query}")
        try:
            content = wikipedia.summary(query, auto_suggest=self.auto_suggest)
            return json.dumps(Document(name=query, content=content).to_dict())
        except DisambiguationError as e:
            return json.dumps({"disambiguation": query, "options": e.options})
        except Exception as e:
            log_error(f"Error searching Wikipedia for '{query}': {e}")
            return json.dumps({"error": str(e)})
