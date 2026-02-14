"""
You can set the following environment variables for your Google Cloud project:

export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="your-location"

Or you can set the following parameters in the BQTools class:

BQTools(
    project="<your-project-id>",
    location="<your-location>",
    dataset="<your-dataset>",
)

NOTE: Instruct the agent to prepend the table name with the project name and dataset name
Describe the table schemas in instructions and use thinking tools for better responses.
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.google_bigquery import GoogleBigQueryTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    instructions=[
        "You are an expert Big query Writer",
        "Always prepend the table name with your_project_id.your_dataset_name when run_sql tool is invoked",
    ],
    tools=[GoogleBigQueryTools(dataset="test_dataset")],
    model=Gemini(id="gemini-3-flash-preview", vertexai=True),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List the tables in the dataset. Tell me about contents of one of the tables",
        markdown=True,
    )
