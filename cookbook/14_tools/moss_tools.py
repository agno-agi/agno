from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.moss import MossTools

# Initialize Moss Tools
# Ensure MOSS_PROJECT_ID and MOSS_PROJECT_KEY are set in your environment
moss_tools = MossTools(default_index_name="moss-demo")

# Create Agent with MossTools
agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),
    tools=[moss_tools],
    description="You are a helpful assistant that can manage and search information in a Moss vector database.",
    instructions=[
        "Use Moss tools to manage and search information in a Moss vector database.",
    ],
)

query = """
First, create an index named 'company-info' if it doesn't exist.
Then add these two facts to it:
1. Our return policy is 30 days.
2. Our support email is support@example.com.
Finally, tell me what the email address is.
"""

agent.print_response(query, markdown=True)
