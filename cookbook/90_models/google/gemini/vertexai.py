"""
To use Vertex AI, with the Gemini Model class, you need to set the following environment variables:

export GOOGLE_GENAI_USE_VERTEXAI="true"
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="your-location"

Or you can set the following parameters in the `Gemini` class:

gemini = Gemini(
    vertexai=True,
    project_id="your-google-cloud-project-id",
    location="your-google-cloud-location",
)
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Gemini(id="gemini-3-flash-preview"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
