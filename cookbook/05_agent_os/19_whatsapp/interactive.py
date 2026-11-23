"""
Send WhatsApp-Native Interactive Messages
=========================================

Give an Agent focused WhatsApp tools for reply buttons, lists, location pins,
and reactions. The interface adds the sender's phone number and incoming
message ID to run context so the Agent can target each tool call correctly.

Prerequisites: OPENAI_API_KEY and the four WHATSAPP_* credentials in README.md
Run: .venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/interactive.py
Try: Ask the bot to recommend an activity nearby
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.websearch import WebSearchTools
from agno.tools.whatsapp import WhatsAppTools

# ---------------------------------------------------------------------------
# Create the Interactive WhatsApp AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="whatsapp-interactive-db",
    db_file="tmp/whatsapp_interactive.db",
)

whatsapp_tools = WhatsAppTools(
    version="v25.0",
    enable_send_text_message=False,
    enable_send_template_message=False,
    enable_send_reply_buttons=True,
    enable_send_list_message=True,
    enable_send_location=True,
    enable_send_reaction=True,
)

concierge = Agent(
    id="whatsapp-concierge",
    name="WhatsApp Concierge",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[whatsapp_tools, WebSearchTools()],
    add_history_to_context=True,
    num_history_runs=5,
    instructions=[
        "Help the user choose a nearby restaurant, activity, or attraction.",
        "The run context contains 'User's WhatsApp number' and "
        "'Incoming WhatsApp message ID'.",
        "Pass the WhatsApp number as recipient to every WhatsApp tool.",
        "Pass the incoming message ID to send_reaction.",
        "Start with one to three reply buttons, then narrow the choice with a list.",
        "Search for current options and send the selected place as a location pin.",
        "A button reply arrives as its displayed title. A list reply arrives as "
        "'title: description', so interpret the visible text rather than relying on IDs.",
        "Use a brief reaction when the interaction is complete.",
        "Do not repeat content already delivered by an interactive WhatsApp tool.",
    ],
)

agent_os = AgentOS(
    id="whatsapp-interactive-os",
    description="An AgentOS using WhatsApp-native interactive message tools.",
    agents=[concierge],
    interfaces=[
        Whatsapp(
            agent=concierge,
            send_user_number_to_context=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the Interactive WhatsApp Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
