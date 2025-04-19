import logging
import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.whatsapp import WhatsAppTools
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configure constants
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
if not VERIFY_TOKEN:
    raise ValueError("WHATSAPP_VERIFY_TOKEN must be set in .envrc")

WEBHOOK_URL = os.getenv("WHATSAPP_WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("WHATSAPP_WEBHOOK_URL must be set in .envrc")

AGENT_STORAGE_FILE = "tmp/whatsapp_agents.db"


def get_whatsapp_agent() -> Agent:
    """Returns an instance of the WhatsApp Agent.

    Returns:
        Agent: The configured WhatsApp agent instance.
    """
    # Initialize WhatsApp tools
    whatsapp = WhatsAppTools()

    # Create and return the agent
    return Agent(
        name="WhatsApp Assistant",
        model=OpenAIChat(id="gpt-4o"),
        tools=[
            whatsapp,
            DuckDuckGoTools(),
        ],
        storage=SqliteAgentStorage(
            table_name="whatsapp_agent", db_file=AGENT_STORAGE_FILE
        ),
        add_history_to_messages=True,
        num_history_responses=3,
        markdown=True,
        description="You are a whatsapp chat agent. You will respond like how people talk to each other on whatsapp, with short sentences and simple language. If user asks you something which requires a web search, use the DuckDuckGoTools to search the web.",
    )
