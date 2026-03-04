"""
Interactive Concierge
=====================

A WhatsApp concierge that uses every interactive UI feature to help
users find restaurants, activities, and entertainment.

Showcases: reply buttons, list messages, location pins, reactions,
mark-as-read, and image sending — all in one conversational flow.

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

agent_db = SqliteDb(db_file="tmp/concierge.db")

concierge_agent = Agent(
    name="Concierge",
    model=Claude(id="claude-sonnet-4-6"),
    tools=[
        WhatsAppTools(
            enable_send_reply_buttons=True,
            enable_send_list_message=True,
            enable_send_location=True,
            enable_send_reaction=True,
            enable_mark_as_read=True,
            enable_send_image=True,
        ),
        WebSearchTools(),
    ],
    db=agent_db,
    instructions=[
        "You are a friendly concierge that helps users find restaurants, activities, and entertainment.",
        "Use WhatsApp interactive features to create a smooth, tap-driven experience.",
        "Follow this flow:",
        "1. Mark the incoming message as read using mark_as_read.",
        "2. Greet the user and ask what they are in the mood for using send_reply_buttons "
        "with options like: Dinner, Drinks, Entertainment.",
        "3. When they pick, ask a follow-up preference using send_reply_buttons "
        "(e.g., cuisine type for dinner, vibe for drinks).",
        "4. Ask for their location or neighborhood (they can type it).",
        "5. Search the web for matching venues in their area.",
        "6. Present the top results using send_list_message with sections "
        "(e.g., 'Top Picks' and 'Hidden Gems'), each row having a title and short description.",
        "7. When they pick a venue from the list, send its location using send_location "
        "with coordinates, name, and address.",
        "8. Send an image of the venue if available using send_image with a URL from search results.",
        "9. React to their original message with a contextual emoji using send_reaction.",
        "Keep messages short and conversational. Use interactive elements instead of asking "
        "the user to type whenever possible.",
    ],
    add_history_to_context=True,
    num_history_runs=10,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[concierge_agent],
    interfaces=[
        Whatsapp(agent=concierge_agent, send_user_number_to_context=True)
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="interactive_concierge:app", port=8000)
