from agno.playground import Playground, serve_playground_app
from agno_assist import agno_support
from agno_assist_voice import agno_assist_voice
from fastapi import FastAPI

# Create and configure the playground app
app = Playground(agents=[agno_support, agno_assist_voice]).get_app()

if __name__ == "__main__":
    serve_playground_app("playground:app", reload=True)
