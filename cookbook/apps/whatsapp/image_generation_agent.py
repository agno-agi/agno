
from agno.app.whatsapp.app import WhatsappAPI
from agno.app.whatsapp.serve import serve_whatsapp_app
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.openai import OpenAITools


image_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[OpenAITools(image_model="gpt-image-1")],
    markdown=True,
    show_tool_calls=True,
    debug_mode=True,
)


app = WhatsappAPI(
    agent=image_agent,
).get_app()

if __name__ == "__main__":
    serve_whatsapp_app("image_generation_agent:app", port=8000, reload=True)