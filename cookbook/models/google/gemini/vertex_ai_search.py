"""Vertex AI Search with Gemini.

Vertex AI Search allows Gemini to search through your data stores,
providing grounded responses based on your private knowledge base.

Prerequisites:
1. Set up Vertex AI Search datastore in Google Cloud Console
2. Export environment variables:
   export GOOGLE_GENAI_USE_VERTEXAI="true"
   export GOOGLE_CLOUD_PROJECT="your-project-id"
   export GOOGLE_CLOUD_LOCATION="your-location"

Run `pip install google-generativeai` to install dependencies.
"""

from agno.agent import Agent
from agno.models.google import Gemini

# Replace with your actual Vertex AI Search datastore ID
# Format: "projects/{project_id}/locations/{location}/collections/default_collection/dataStores/{datastore_id}"
datastore_id = "projects/your-project-id/locations/global/collections/default_collection/dataStores/your-datastore-id"

agent = Agent(
    model=Gemini(
        id="gemini-2.5-flash",
        vertexai_search=True,
        vertexai_search_datastore=datastore_id,
        vertexai=True,  # Use Vertex AI endpoint
    ),
    markdown=True,
)

# Ask questions that can be answered from your knowledge base
agent.print_response("What are our company's policies regarding remote work?")
