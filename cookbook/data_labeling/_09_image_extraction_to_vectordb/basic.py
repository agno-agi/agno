"""
Image Extraction to Vector DB - Basic
=====================================

End-to-end labeling pipeline:
    extract structured fields from images -> embed -> store -> search.

1. An agent extracts an ImageDescription from each image.
2. The description is flattened to a single searchable string.
3. The string is embedded with OpenAIEmbedder and stored in LanceDb.
4. We query the index with natural language.

Writes to tmp/lancedb/ under the repo root.
"""

from typing import List

from agno.agent import Agent
from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.media import Image
from agno.models.openai import OpenAIResponses
from agno.vectordb.lancedb import LanceDb, SearchType
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ImageDescription(BaseModel):
    subject: str = Field(..., description="The main subject of the image")
    setting: str = Field(..., description="Where the image takes place")
    mood: str = Field(..., description="Overall mood or tone")
    key_objects: List[str] = Field(
        default_factory=list, description="Up to five notable objects"
    )


# ---------------------------------------------------------------------------
# Create Extraction Agent
# ---------------------------------------------------------------------------
extractor = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="You describe images as structured, search-friendly metadata.",
    output_schema=ImageDescription,
)


# ---------------------------------------------------------------------------
# Vector DB
# ---------------------------------------------------------------------------
vector_db = LanceDb(
    uri="tmp/lancedb",
    table_name="data_labeling_images",
    search_type=SearchType.vector,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def describe(url: str) -> ImageDescription:
    return extractor.run("Describe this image.", images=[Image(url=url)]).content


def to_searchable_text(d: ImageDescription) -> str:
    return (
        f"Subject: {d.subject}. Setting: {d.setting}. Mood: {d.mood}. "
        f"Objects: {', '.join(d.key_objects)}."
    )


def index_images(urls: List[str]) -> None:
    vector_db.create()
    docs: List[Document] = []
    for url in urls:
        description = describe(url)
        docs.append(
            Document(
                name=url,
                content=to_searchable_text(description),
                meta_data={"url": url, "subject": description.subject},
            )
        )
    vector_db.insert(content_hash="image_batch_1", documents=docs)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    urls = [
        "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/a/a8/Tour_Eiffel_Wikimedia_Commons.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/4/4d/Cat_November_2010-1a.jpg",
    ]
    index_images(urls)

    for query in ["a famous landmark", "a sleeping pet"]:
        results = vector_db.search(query, limit=2)
        pprint({"query": query, "hits": [r.meta_data for r in results]})
