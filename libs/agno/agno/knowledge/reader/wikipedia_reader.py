from typing import List

from agno.document import Document
from agno.knowledge.reader.base import Reader
from agno.utils.log import log_info

try:
    import wikipedia  # noqa: F401
except ImportError:
    raise ImportError("The `wikipedia` package is not installed. Please install it via `pip install wikipedia`.")


class WikipediaReader(Reader):
    auto_suggest: bool = True

    def read(self, topic: str) -> List[Document]:
        print(f"Reading topic: {topic}")
        summary = None
        try:
            summary = wikipedia.summary(topic, auto_suggest=self.auto_suggest)

        except wikipedia.exceptions.PageError:
            summary = None
            log_info(f"PageError: Page not found.")

        # Only create Document if we successfully got a summary
        if summary:
            return [
                Document(
                    name=topic,
                    meta_data={"topic": topic},
                    content=summary,
                )
            ]
        return []
