"""
This example demonstrates how to use knowledge_filters inheritance from Team to member agents.

When a Team has knowledge_filters defined, it can automatically propagate those filters
to its member agents using the `inherit_knowledge_filters_to_agents` property.

Three inheritance modes are available:
- "replace": Team filters completely replace agent filters
- "merge_team_priority": Merge both filters, team wins on key conflicts
- "merge_agent_priority": Merge both filters, agent wins on key conflicts

This is useful when you want all team members to search within a specific subset
of the knowledge base (e.g., department-specific documents) while still allowing
agents to have their own specialized filters.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.lancedb import LanceDb

# Download sample CVs for demonstration
downloaded_cv_paths = download_knowledge_filters_sample_data(
    num_files=5, file_extension=SampleDataFileExtension.PDF
)

# Initialize LanceDB vector database
vector_db = LanceDb(
    table_name="team_knowledge_inheritance_demo",
    uri="tmp/lancedb",
)

# Create knowledge base
knowledge_base = Knowledge(vector_db=vector_db)

# Add documents with metadata for filtering
knowledge_base.add_contents(
    [
        {
            "path": downloaded_cv_paths[0],
            "metadata": {
                "user_id": "jordan_mitchell",
                "department": "engineering",
                "document_type": "cv",
            },
        },
        {
            "path": downloaded_cv_paths[1],
            "metadata": {
                "user_id": "taylor_brooks",
                "department": "engineering",
                "document_type": "cv",
            },
        },
        {
            "path": downloaded_cv_paths[2],
            "metadata": {
                "user_id": "morgan_lee",
                "department": "research",
                "document_type": "cv",
            },
        },
        {
            "path": downloaded_cv_paths[3],
            "metadata": {
                "user_id": "casey_jordan",
                "department": "research",
                "document_type": "cv",
            },
        },
        {
            "path": downloaded_cv_paths[4],
            "metadata": {
                "user_id": "alex_rivera",
                "department": "marketing",
                "document_type": "cv",
            },
        },
    ],
    reader=PDFReader(chunk=True),
)

# --- Example 1: Replace Mode ---
# Team filters completely replace agent filters

# Agent with its own filters (will be replaced by team filters)
researcher_agent = Agent(
    name="Researcher",
    role="Search and analyze documents",
    knowledge=knowledge_base,
    knowledge_filters={"document_type": "reports"},  # This will be replaced
    model=OpenAIChat(id="gpt-4o-mini"),
)

# Team with department filter - will replace agent's filter
team_replace_mode = Team(
    name="Engineering Team (Replace Mode)",
    members=[researcher_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_base,
    knowledge_filters={"department": "engineering"},  # Only engineering docs
    inherit_knowledge_filters_to_agents=True,
    knowledge_filters_inheritance_mode="replace",
    show_members_responses=True,
    markdown=True,
)

# --- Example 2: Merge with Team Priority ---
# Both filters are merged, team wins on conflicts

# Agent with specific document type filter
analyst_agent = Agent(
    name="Analyst",
    role="Analyze research documents",
    knowledge=knowledge_base,
    knowledge_filters={"document_type": "cv", "year": 2025},  # Agent's filters
    model=OpenAIChat(id="gpt-4o-mini"),
)

# Team filters will be merged with agent filters, team wins on conflicts
team_merge_team_priority = Team(
    name="Research Team (Merge Team Priority)",
    members=[analyst_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_base,
    knowledge_filters={"department": "research"},  # Team adds department filter
    inherit_knowledge_filters_to_agents=True,
    knowledge_filters_inheritance_mode="merge_team_priority",
    show_members_responses=True,
    markdown=True,
)
# Result: Agent will search with {"department": "research", "document_type": "cv", "year": 2025}

# --- Example 3: Merge with Agent Priority ---
# Both filters are merged, agent wins on conflicts

# Agent with specific filters it wants to preserve
specialist_agent = Agent(
    name="Specialist",
    role="Find specific user documents",
    knowledge=knowledge_base,
    knowledge_filters={"user_id": "alex_rivera"},  # Agent's specific filter
    model=OpenAIChat(id="gpt-4o-mini"),
)

# Team provides general department filter, but agent's user_id takes priority
team_merge_agent_priority = Team(
    name="Marketing Team (Merge Agent Priority)",
    members=[specialist_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_base,
    knowledge_filters={"department": "marketing", "document_type": "cv"},
    inherit_knowledge_filters_to_agents=True,
    knowledge_filters_inheritance_mode="merge_agent_priority",
    show_members_responses=True,
    markdown=True,
)
# Result: Agent will search with {"department": "marketing", "document_type": "cv", "user_id": "alex_rivera"}

if __name__ == "__main__":
    print("=" * 60)
    print("Example 1: Replace Mode")
    print("Team filter replaces agent filter")
    print("=" * 60)
    team_replace_mode.print_response(
        "Tell me about the engineering candidates",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Example 2: Merge with Team Priority")
    print("Merged filters: department from team + document_type & year from agent")
    print("=" * 60)
    team_merge_team_priority.print_response(
        "Summarize the research team CVs",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Example 3: Merge with Agent Priority")
    print("Agent's user_id filter preserved, team's department added")
    print("=" * 60)
    team_merge_agent_priority.print_response(
        "What can you tell me about Alex Rivera?",
        stream=True,
    )
