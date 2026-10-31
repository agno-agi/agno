"""
Elasticsearch Metadata Filtering
================================

Filters narrow a search to the documents whose metadata matches, before ranking.
Elasticsearch supports every form Agno's filter dict can express:

    {"year": 2025}                  equality
    {"year": [2024, 2025]}          any of these
    {"year": {"$in": [2024, 2025]}} the same thing, written as an operator
    {"year": {"gte": 2024}}         a range
    {"a": 1, "b": 2}                both must match

Two notes specific to this backend:

- Values are matched exactly, not by relevance. Filtering on "cv" finds documents
  whose document_type is exactly "cv", never "cv_draft".
- A date written as a string ("2024-01-15") filters and ranges like any other string.
  The index turns off date detection so these stay text, which is what lets an
  equality filter match them.

Requirements:
- ./cookbook/scripts/run_elasticsearch.sh
- uv pip install "elasticsearch[async]"
- OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.elasticsearch import Elasticsearch

# Download all sample CVs and get their paths
downloaded_cv_paths = download_knowledge_filters_sample_data(
    num_files=5, file_extension=SampleDataFileExtension.PDF
)

INDEX_NAME = "filtering-cv"

vector_db = Elasticsearch(index_name=INDEX_NAME, url="http://localhost:9200")

# Start clean so re-running does not stack duplicates from a previous run
if vector_db.exists():
    vector_db.drop()

# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
# Metadata attached at load time is what the filters below match against.

knowledge = Knowledge(
    name="Elasticsearch Knowledge Base",
    description="A knowledge base for Elasticsearch metadata filtering",
    vector_db=vector_db,
)

knowledge.insert_many(
    [
        {
            "path": downloaded_cv_paths[0],
            "metadata": {
                "user_id": "jordan_mitchell",
                "document_type": "cv",
                "year": 2025,
                "published_on": "2025-03-14",
            },
        },
        {
            "path": downloaded_cv_paths[1],
            "metadata": {
                "user_id": "taylor_brooks",
                "document_type": "cv",
                "year": 2025,
                "published_on": "2025-07-02",
            },
        },
        {
            "path": downloaded_cv_paths[2],
            "metadata": {
                "user_id": "morgan_lee",
                "document_type": "cv",
                "year": 2024,
                "published_on": "2024-01-15",
            },
        },
        {
            "path": downloaded_cv_paths[3],
            "metadata": {
                "user_id": "casey_jordan",
                "document_type": "cv",
                "year": 2024,
                "published_on": "2024-09-30",
            },
        },
        {
            "path": downloaded_cv_paths[4],
            "metadata": {
                "user_id": "alex_rivera",
                "document_type": "cv",
                "year": 2023,
                "published_on": "2023-11-08",
            },
        },
    ]
)


# ---------------------------------------------------------------------------
# Run Filters
# ---------------------------------------------------------------------------


def show(label: str, filters: dict) -> None:
    """Search with one filter and report how many documents survived it."""
    results = knowledge.search("experience and skills", max_results=10, filters=filters)
    owners = sorted({d.meta_data.get("user_id", "?") for d in results})
    print(f"{label}")
    print(f"   filter:  {filters}")
    print(f"   matched: {len(results)} chunks from {owners}")
    print()


if __name__ == "__main__":
    print()
    show("Equality - one person's CV", {"user_id": "jordan_mitchell"})
    show("Equality on a number", {"year": 2024})
    show("Equality on a date string", {"published_on": "2024-01-15"})
    show("Any of these years", {"year": [2024, 2025]})
    show("The same thing as an operator", {"year": {"$in": [2024, 2025]}})
    show("Numeric range - 2024 onwards", {"year": {"gte": 2024}})
    show(
        "Date range - second half of 2024 onwards",
        {"published_on": {"gte": "2024-07-01"}},
    )
    show("Two filters, both must match", {"document_type": "cv", "year": 2025})
    show("A filter nothing matches", {"user_id": "nobody"})

    # ---------------------------------------------------------------------------
    # Filters through an agent
    # ---------------------------------------------------------------------------
    # knowledge_filters applies the same filtering to whatever the agent retrieves,
    # so it can only answer from the documents the filter allows.

    agent = Agent(knowledge=knowledge, search_knowledge=True)

    agent.print_response(
        "Tell me about Jordan Mitchell's experience and skills",
        knowledge_filters={"user_id": "jordan_mitchell"},
        markdown=True,
    )
