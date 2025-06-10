from agno.agent import Agent
from agno.app.whatsapp.app import WhatsappAPI
from agno.models.google import Gemini

media_agent = Agent(
    name="Media Agent",
    model=Gemini(id="gemini-2.0-flash"),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
)

whatsapp_app = WhatsappAPI(
    agent=media_agent,
    name="Media Agent",
    app_id="media_agent",
    description="A agent that can send media to the user.",
)

app = whatsapp_app.get_app()

if __name__ == "__main__":
    whatsapp_app.serve(app="agent_with_media:app", port=8000, reload=True)
