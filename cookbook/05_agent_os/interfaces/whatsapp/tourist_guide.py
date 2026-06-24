"""
Tourist Guide
==============

A WhatsApp agent that recommends tourist spots using interactive menus.

It asks the user questions via reply buttons and list messages, searches the
web for top attractions, and sends a location pin for its recommendation.

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  ANTHROPIC_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.websearch import WebSearchTools
from agno.tools.whatsapp import WhatsAppTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent_db = SqliteDb(db_file="tmp/tourist_guide.db")

tourist_agent = Agent(
    name="Tourist Guide",
    model=Claude(id="claude-sonnet-4-6"),
    tools=[
        WhatsAppTools(
            enable_send_reply_buttons=True,
            enable_send_list_message=True,
            enable_send_location=True,
            enable_send_image=True,
        ),
        WebSearchTools(),
    ],
    db=agent_db,
    instructions=[
        "You are a friendly tourist guide that recommends places to visit.",
        "When the conversation starts, greet the user and ask what type of trip they want "
        "using send_reply_buttons with options like: Adventure, Culture, Relaxation.",
        "Then ask which region they prefer using a send_list_message with sections for "
        "different continents and rows for popular destinations.",
        "After the user picks a destination, use DuckDuckGo to search for the top tourist "
        "spots there and summarise the best 3 options as a text message.",
        "Finally, send a location pin for your top recommendation using send_location.",
        "Keep messages short and conversational.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[tourist_agent],
    interfaces=[Whatsapp(agent=tourist_agent, send_user_number_to_context=True)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="tourist_guide:app", reload=True)
