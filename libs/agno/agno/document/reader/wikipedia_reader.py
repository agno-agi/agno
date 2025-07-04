from typing import List

from agno.document import Document
from agno.document.reader.base import Reader

try:
    import wikipedia  # noqa: F401
except ImportError:
    raise ImportError("The `wikipedia` package is not installed. Please install it via `pip install wikipedia`.")


class WikipediaReader(Reader):
    auto_suggest: bool = True

    def read(self, topics: List[str]) -> List[Document]:
        documents = []
        for topic in topics:
            summary = None
            try:
                summary = wikipedia.summary(topic, auto_suggest=self.auto_suggest)

            except wikipedia.exceptions.PageError:
                print(f"PageError: Page not found. Trying search...")
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
                    print(f"Unexpected error for topic during search '{topic}': {e}")
                    continue

            except Exception as e:
                print(f"Unexpected error for topic '{topic}': {e}")
                continue

            # Only create Document if we successfully got a summary
            if summary:
                documents.append(
                    Document(
                        name=topic,
                        meta_data={"topic": topic},
                        content=summary,
                    )
                )
        return documents
