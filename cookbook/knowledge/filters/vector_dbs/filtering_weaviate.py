from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.weaviate import Distance, VectorIndex, Weaviate

# Download all sample CVs and get their paths
downloaded_cv_paths = download_knowledge_filters_sample_data(
    num_files=5, file_extension=SampleDataFileExtension.PDF
)

# Step 1: Initialize knowledge with documents and metadata
# ------------------------------------------------------------------------------
# When initializing the knowledge, we can attach metadata that will be used for filtering
# This metadata can include user IDs, document types, dates, or any other attributes

vector_db = Weaviate(
    collection="recipes",
    vector_index=VectorIndex.HNSW,
    distance=Distance.COSINE,
    local=False,  # Set to False if using Weaviate Cloud and True if using local instance
)

knowledge = Knowledge(
    name="Weaviate Knowledge Base",
    description="A knowledge base for Weaviate",
    vector_db=vector_db,
)

knowledge.add_contents(
    [
        {
            "path": downloaded_cv_paths[0],
            "metadata": {
                "user_id": "jordan_mitchell",
                "document_type": "cv",
                "year": 2025,
            },
        },
        {
            "path": downloaded_cv_paths[1],
            "metadata": {
                "user_id": "taylor_brooks",
                "document_type": "cv",
                "year": 2025,
            },
        },
        {
            "path": downloaded_cv_paths[2],
            "metadata": {
                "user_id": "morgan_lee",
                "document_type": "cv",
                "year": 2025,
            },
        },
        {
            "path": downloaded_cv_paths[3],
            "metadata": {
                "user_id": "casey_jordan",
                "document_type": "cv",
                "year": 2025,
            },
        },
        {
            "path": downloaded_cv_paths[4],
            "metadata": {
                "user_id": "alex_rivera",
                "document_type": "cv",
                "year": 2025,
            },
        },
    ]
)

# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------

agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response(
    "Tell me about Jordan Mitchell's experience and skills",
    knowledge_filters={"user_id": "jordan_mitchell"},
    markdown=True,
)
