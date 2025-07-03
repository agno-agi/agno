from typing import Iterator, List

from agno.document import Document
from agno.knowledge.agent import AgentKnowledge

try:
    import wikipedia  # noqa: F401
except ImportError:
    raise ImportError("The `wikipedia` package is not installed. Please install it via `pip install wikipedia`.")


class WikipediaKnowledgeBase(AgentKnowledge):
    topics: List[str] = []
    auto_suggest: bool = True

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for topic in self.topics:
            summary = None
            try:
                summary = wikipedia.summary(topic, auto_suggest=self.auto_suggest)
            except wikipedia.exceptions.DisambiguationError as e:
                # Handle disambiguation: pick the first option
                try:
                    summary = wikipedia.summary(e.options[0], auto_suggest=self.auto_suggest)
                except Exception as inner_e:
                    print(f"Failed to get summary for disambiguation option '{e.options[0]}': {inner_e}")
                    continue
            except wikipedia.exceptions.PageError:
                # Fallback: try searching and use first result
                try:
                    search_results = wikipedia.search(topic)
                    if search_results:
                        try:
                            summary = wikipedia.summary(search_results[0], auto_suggest=self.auto_suggest)
                        except Exception as inner_e:
                            print(f"Failed to get summary for search result '{search_results[0]}': {inner_e}")
                            continue
                    else:
                        print(f"No Wikipedia page found for topic: {topic}")
                        continue
                except Exception as e:
                    print(f"Unexpected error for topic '{topic}': {e}")
                    continue
            except Exception as e:
                print(f"Unexpected error for topic '{topic}': {e}")
                continue

            # Only yield Document if we successfully got a summary
            if summary:
                yield [
                    Document(
                        name=topic,
                        meta_data={"topic": topic},
                        content=summary,
                    )
                ]
