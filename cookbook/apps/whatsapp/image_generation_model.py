from agno.agent import Agent
from agno.app.whatsapp.app import WhatsappAPI
from agno.app.whatsapp.serve import serve_whatsapp_app
from agno.models.google import Gemini

image_agentg = Agent(
    model=Gemini(
        id="gemini-2.0-flash-exp-image-generation",
        response_modalities=["Text", "Image"],
    ),
    debug_mode=True,
)

app = WhatsappAPI(
    agent=image_agentg,
).get_app()

if __name__ == "__main__":
    serve_whatsapp_app("image_generation_model:app", port=8000, reload=True)
