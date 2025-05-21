from agno.agent import Agent
from agno.app.whatsapp.app import WhatsappAPI
from agno.app.whatsapp.serve import serve_whatsapp_app
from agno.models.google import Gemini

media_agent = Agent(
    name="Media Agent",
    model=Gemini(id="gemini-2.0-flash"),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
)

app = WhatsappAPI(
    agent=media_agent,
).get_app()

if __name__ == "__main__":
    serve_whatsapp_app("agent_with_media:app", port=8000, reload=True)
