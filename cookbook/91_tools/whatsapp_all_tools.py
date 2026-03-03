"""
WhatsApp All Tools Cookbook
---------------------------

Demonstrates all 9 sync tools available in WhatsAppTools on this branch.

Pre-existing tools (enabled by default):
  - send_text_message      : Send a plain text message
  - send_template_message  : Send a pre-approved Meta template message

New tools added in this PR (disabled by default, use all=True to enable):
  - send_reply_buttons     : Send an interactive message with up to 3 quick-reply buttons
  - send_list_message      : Send an interactive list with sections and selectable rows
  - send_image             : Send an image by public URL or uploaded media ID
  - send_document          : Send a document (PDF, DOCX, etc.) by URL or media ID
  - send_location          : Send a location pin with coordinates, name, and address
  - send_reaction          : React to an existing message with an emoji
  - mark_as_read           : Send a read receipt for a received message

Setup (environment variables required):
  WHATSAPP_ACCESS_TOKEN      - Your Meta app access token
  WHATSAPP_PHONE_NUMBER_ID   - The phone number ID from Meta Developer Portal
  WHATSAPP_RECIPIENT_WAID    - Default recipient phone number (e.g. 15551234567)
  WHATSAPP_VERSION           - API version, defaults to v22.0

Notes:
  - Tools are sync-only; the async boundary is at the router/webhook layer.
  - Use all=True to enable every tool at once (shown below).
  - Use per-flag enables (enable_send_image=True, etc.) to expose only specific tools.
  - First-time outreach to a number requires a pre-approved template message.
  - Reactions and mark_as_read require a valid wamid from a received/sent message.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.whatsapp import WhatsAppTools

# ---------------------------------------------------------------------------
# Agent with all 9 tools enabled
# ---------------------------------------------------------------------------

agent = Agent(
    name="WhatsApp Assistant",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WhatsAppTools(all=True)  # enables all 9 tools at once
    ],
    instructions=[
        "You are a WhatsApp assistant that can send messages, media, locations, and reactions.",
        "Always confirm what was sent and include the message_id from the response.",
        "If a tool returns an error, report it clearly and do not retry automatically.",
    ],
)

# ---------------------------------------------------------------------------
# Example runs — each exercises a different tool
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    recipient = (
        "+15551234567"  # replace with a number registered in your test environment
    )

    # 1. send_text_message
    print("--- send_text_message ---")
    agent.print_response(
        f"Send a text message to {recipient} saying: Hello from the Agno WhatsApp demo!"
    )

    # 2. send_template_message
    # Requires an approved template in your Meta Business account.
    print("--- send_template_message ---")
    agent.print_response(
        f"Send the 'hello_world' template in English (en_US) to {recipient}."
    )

    # 3. send_reply_buttons
    # Max 3 buttons; each button title max 20 chars.
    print("--- send_reply_buttons ---")
    agent.print_response(
        f"Send an interactive button message to {recipient} with body text "
        "'Would you like to continue?' and three buttons: "
        "id='yes' title='Yes', id='no' title='No', id='later' title='Remind me later'. "
        "Add a footer 'Choose one option'."
    )

    # 4. send_list_message
    # Sections with selectable rows; useful for menus.
    print("--- send_list_message ---")
    agent.print_response(
        f"Send a list message to {recipient} with: "
        "header='Main Menu', "
        "body='Choose a support category below.', "
        "button text='Open Menu', "
        "one section titled 'Categories' with three rows: "
        "id='billing' title='Billing', "
        "id='technical' title='Technical Support', "
        "id='general' title='General Inquiry'."
    )

    # 5. send_image
    # Provide a publicly accessible image URL.
    print("--- send_image ---")
    agent.print_response(
        f"Send an image to {recipient} using the URL "
        "https://cdn.prod.website-files.com/6796d350b8c706e4533e7e32/6796d350b8c706e4533e8011_Agno%20Logo.png"
        "with caption 'Check out the Agno logo!'."
    )

    # 6. send_document
    # Provide a publicly accessible document URL.
    print("--- send_document ---")
    agent.print_response(
        f"Send a PDF document to {recipient} from the URL "
        "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf "
        "with filename 'thairecipes.pdf' and caption 'Thai Recipes!'."
    )

    # 7. send_location
    print("--- send_location ---")
    agent.print_response(
        f"Send a location pin to {recipient} for the Eiffel Tower: "
        "latitude=48.8584, longitude=2.2945, "
        "name='Eiffel Tower', address='Champ de Mars, 5 Avenue Anatole France, Paris'."
    )

    # 8. send_reaction
    # Replace WAMID below with a real message ID received from WhatsApp.
    print("--- send_reaction ---")
    wamid = "wamid.REPLACE_WITH_REAL_MESSAGE_ID"
    agent.print_response(
        f"React to the message with id {wamid} from {recipient} using a thumbs-up emoji."
    )

    # 9. mark_as_read
    # Replace WAMID below with a real inbound message ID.
    print("--- mark_as_read ---")
    wamid_inbound = "wamid.REPLACE_WITH_REAL_INBOUND_MESSAGE_ID"
    agent.print_response(f"Mark the message {wamid_inbound} as read.")
