"""
This example demonstrates how to use agentic knowledge filters with teams.

Agentic knowledge filters allow the AI to dynamically determine which documents
to search based on the query context, rather than using predefined filters.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.lancedb import LanceDb

# Download all sample CVs and get their paths
downloaded_cv_paths = download_knowledge_filters_sample_data(
    num_files=5, file_extension=SampleDataFileExtension.PDF
)

# Initialize LanceDB vector database
# By default, it stores data in /tmp/lancedb
vector_db = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",  # You can change this path to store data elsewhere
)

# Create knowledge base
knowledge = Knowledge(
    vector_db=vector_db,
)

# Add documents with metadata for agentic filtering
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

# Create knowledge search agent with filter awareness
web_agent = Agent(
    name="Knowledge Search Agent",
    role="Handle knowledge search",
    knowledge=knowledge,
    model=OpenAIChat(id="o3-mini"),
    instructions=["Always take into account filters"],
)

# Create team with agentic knowledge filters enabled
team_with_knowledge = Team(
    name="Team with Knowledge",
    members=[
        web_agent
    ],  # If you omit the member, the leader will search the knowledge base itself.
    model=OpenAIChat(id="o3-mini"),
    knowledge=knowledge,
    show_members_responses=True,
    markdown=True,
    enable_agentic_knowledge_filters=True,  # Allow AI to determine filters
)

# Test agentic knowledge filtering
team_with_knowledge.print_response(
    "Tell me about Jordan Mitchell's work and experience with user_id as jordan_mitchell"
)
