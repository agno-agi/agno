"""
You can set the following environment variables for your Google Cloud project:

export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="your-location"

Or you can set the following parameters in the BQTools class:

BQTools(
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_CLOUD_DATASET",
)

NOTE: Instruct the agent to prepend the table name with the project name and dataset name 
Describe the table schemas in instructions and use thinking tools for better responses.
"""

import os
from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.bigquery import BQTools

agent = Agent(
    instructions=[
        "You are an expert Big query Writer",
        "Always prepend the table name with your_project_id.your_dataset_name when run_sql tool is invoked",
        ],
        
    tools=[BQTools("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "DATASET_ID")],
    show_tool_calls=True,
    model=Gemini(id="gemini-2.0-flash", vertexai=True, project_id="GOOGLE_CLOUD_PROJECT", location="us-central1"), 
)

agent.print_response(
    "List the tables in the dataset. Tell me about contents of one of the tables",
    markdown=True,
)