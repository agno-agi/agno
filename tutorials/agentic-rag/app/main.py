"""Docs Assistant - AgentOS Application"""

from pathlib import Path

from agno.os import AgentOS

from agents.docs_assistant import get_docs_assistant, get_knowledge, load_knowledge

os_config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# Load knowledge base with documents
knowledge = get_knowledge()
load_knowledge(knowledge)

docs_assistant = get_docs_assistant(model_id="gpt-4o-mini", knowledge=knowledge)

# Create the AgentOS
agent_os = AgentOS(
    id="docs-assistant",
    agents=[docs_assistant],
    config=os_config_path,
)
app = agent_os.get_app()

if __name__ == "__main__":
    import os
    # Disable reload in Docker (production)
    reload = os.environ.get("RELOAD", "false").lower() == "true"
    port = int(os.environ.get("PORT", 7777))
    agent_os.serve(app="app.main:app", host="0.0.0.0", port=port, reload=reload)
