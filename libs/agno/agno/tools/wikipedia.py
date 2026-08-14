import json
from typing import Callable, List, Optional

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
    """Tools for searching Wikipedia articles.

    Provides search functionality to retrieve Wikipedia content. When a Knowledge base
    is provided, an additional tool that stores search results in the knowledge base
    is also registered.

    Args:
        knowledge: Optional Knowledge base to store search results.
        auto_suggest: Let Wikipedia find a valid page title for the query. Defaults to True.
        search_wikipedia: Enable basic Wikipedia search tool. Defaults to True.
        search_wikipedia_and_update_knowledge_base: Enable search with knowledge base update.
            Only available when knowledge is provided. Defaults to True.
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        knowledge: Optional[Knowledge] = None,
        auto_suggest: bool = True,
        search_wikipedia: bool = True,
        search_wikipedia_and_update_knowledge_base: bool = True,
        all: bool = False,
        **kwargs,
    ):
        tools: List[Callable] = []

        self.auto_suggest = auto_suggest
        self.knowledge: Optional[Knowledge] = knowledge

        if all or search_wikipedia:
            tools.append(self.search_wikipedia)  # type: ignore
        if isinstance(self.knowledge, Knowledge) and (all or search_wikipedia_and_update_knowledge_base):
            tools.append(self.search_wikipedia_and_update_knowledge_base)

        super().__init__(name="wikipedia_tools", tools=tools, **kwargs)

    def search_wikipedia_and_update_knowledge_base(self, topic: str) -> str:
        """Search Wikipedia for a topic and add results to the knowledge base.

        Use this function to get information which does not exist in the knowledge base.

        Args:
            topic: The topic to search Wikipedia and add to knowledge base.

        Returns:
            JSON string containing relevant documents from Wikipedia knowledge base.
        """

        if self.knowledge is None:
            return json.dumps({"error": "Knowledge not provided"})

        log_debug(f"Adding to knowledge: {topic}")
        self.knowledge.insert(
            topics=[topic],
            reader=WikipediaReader(auto_suggest=self.auto_suggest),
        )
        log_debug(f"Searching knowledge: {topic}")
        relevant_docs: List[Document] = self.knowledge.search(query=topic)
        return json.dumps([doc.to_dict() for doc in relevant_docs])

    def search_wikipedia(self, query: str) -> str:
        """Search Wikipedia for a query.

        Args:
            query: The query to search for.

        Returns:
            JSON string containing the Wikipedia article summary or disambiguation options.
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
