from agno.playground import Playground, serve_playground_app
from agno_assist import agno_support
from agno_assist_voice import agno_assist_voice
from fastapi import FastAPI

# Create and configure the playground app
playground_app = Playground(
    agents=[agno_support, agno_assist_voice],
    name="Playground-hackathon",
    app_id="playground-hackathon",
    description="A playground for testing and playing with Agno",
)

app = playground_app.get_app()

if __name__ == "__main__":
    playground_app.serve(app="playground:app", reload=True)
