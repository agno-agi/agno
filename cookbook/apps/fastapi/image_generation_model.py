from agno.agent import Agent
from agno.app.fastapi import FastAPIApp
from agno.models.google import Gemini

image_agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash-exp-image-generation",
        response_modalities=["Text", "Image"],
    ),
    agent_id="image_model",
)

fastapi_app = FastAPIApp(
    agents=[image_agent],
    name="Image Generation Model",
    app_id="image_generation_model",
    description="A model that generates images using the Gemini API.",
)

app = fastapi_app.get_app()

if __name__ == "__main__":
    fastapi_app.serve(app="image_generation_model:app", port=8001, reload=True)
