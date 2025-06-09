from agno.agent import Agent
from agno.app.whatsapp.app import WhatsappAPI
from agno.models.google import Gemini

image_agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash-exp-image-generation",
        response_modalities=["Text", "Image"],
    ),
    debug_mode=True,
)

whatsapp_app = WhatsappAPI(
    agent=image_agent,
    name="Image Generation Model",
    app_id="image_generation_model",
    description="A model that generates images using the Gemini API.",
)

app = whatsapp_app.get_app()

if __name__ == "__main__":
    whatsapp_app.serve(app="image_generation_model:app", port=8000, reload=True)
