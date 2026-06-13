from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.tensorlake import TensorLakeTools
from dotenv import load_dotenv

# For this example, you will need a Tensorlake and an OpenAI API key.
# Make sure to set these in your environment variables or .env file.
load_dotenv()

agent_instructions = """You have access to a document via TensorLake tools. Follow these steps:

    1. ALWAYS use the parse_document_to_markdown tool first when asked about document analysis.
    2. The document is already loaded - no need to ask for uploads.
    3. For signatures specifically, ALWAYS set detect_signature=True.
    """

# Basic agent with document parsing capabilities
agent = Agent(
    name="Tensorlake Document Parser Agent",
    description="You are an AI agent that can parse documents using Tensorlake tool and answer questions.",
    instructions=agent_instructions,
    model=OpenAIChat(id="gpt-4o"),
    tools=[TensorLakeTools()],
    show_tool_calls=True,
)

# This is using a sample real estate document with signatures
# You can replace this with any PDF document containing signatures
path = "https://pub-226479de18b2493f96b64c6674705dd8.r2.dev/real-estate-purchase-all-signed.pdf"

# Define the question to be asked and create the agent
question = f"What contextual information can you extract about the signatures in my document found at {path}?"

agent.print_response(question)
