from agno.agent import Agent
from agno.models.google import Gemini

# To use Vertex AI with explicit credentials, you can pass a
# google.oauth2.service_account.Credentials object to the Gemini class.

# 1. Load your service account credentials (example using a JSON file)
# from google.oauth2 import service_account
# credentials = service_account.Credentials.from_service_account_file('path/to/your/service-account.json')

# For demonstration, we'll assume credentials is provided
credentials = None  # Replace with your actual credentials object

# 2. Initialize the Gemini model with the credentials parameter
model = Gemini(
    id="gemini-2.0-flash-001",
    vertexai=True,
    project_id="your-google-cloud-project-id",
    location="us-central1",
    credentials=credentials,
)

# 3. Create the Agent
agent = Agent(model=model, markdown=True)

# 4. Use the Agent
agent.print_response(
    "Explain how explicit credentials help in production environments."
)
