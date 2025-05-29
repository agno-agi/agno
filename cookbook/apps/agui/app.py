from agent import chat_agent
from agno.app.agui import AGUIApp

# Create the AG-UI app
agui_app = AGUIApp(
    agent=chat_agent,
    name="Basic AG-UI Agent",
    app_id="basic_agui_agent",
    description="A basic agent that demonstrates AG-UI protocol integration.",
)

# Get the FastAPI app instance
app = agui_app.get_app()

if __name__ == "__main__":
    # Serve the app
    agui_app.serve(app="app:app", port=8000, reload=True)
