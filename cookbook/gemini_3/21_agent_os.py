"""
Agent OS - Deploy All Agents as a Web Service
===============================================
All agents, teams, and workflows from steps 1-20 deployed as a web service.
Agent OS provides a web interface for interacting with your agents --
chat with them, explore sessions, monitor traces, and manage knowledge.

This is the capstone of the guide: everything you built, served on one endpoint.

How to use:
1. Start the server: python cookbook/gemini_3/21_agent_os.py
2. Visit https://os.agno.com in your browser
3. Add your local endpoint: http://localhost:7777
4. Select any agent, team, or workflow and start chatting

Key concepts:
- AgentOS: Wraps agents, teams, and workflows into a FastAPI web service
- get_app(): Returns a FastAPI app you can customize
- serve(): Starts the server with uvicorn (hot-reload enabled)
- tracing=True: Enables request tracing in the Agent OS UI

Prerequisites:
- GOOGLE_API_KEY environment variable set
"""

import importlib
import sys
from pathlib import Path

from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Import agents from numbered files
# Python can't import modules starting with digits directly, so we use importlib
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))


def _import(module_name: str, attr: str):
    return getattr(importlib.import_module(module_name), attr)


# Import agents from earlier steps
chat_agent = _import("1_basic", "chat_agent")
finance_agent = _import("2_tools", "finance_agent")
critic_agent = _import("3_structured_output", "critic_agent")
news_agent = _import("4_search", "news_agent")
fact_checker = _import("5_grounding", "fact_checker")
url_agent = _import("6_url_context", "url_agent")
image_agent = _import("8_image_input", "image_agent")
doc_reader = _import("13_pdf_input", "doc_reader")
recipe_agent = _import("17_knowledge", "recipe_agent")
tutor_agent = _import("18_memory", "tutor_agent")
content_team = _import("19_team", "content_team")
research_pipeline = _import("20_workflow", "research_pipeline")

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="Gemini Agent OS",
    agents=[
        chat_agent,
        finance_agent,
        critic_agent,
        news_agent,
        fact_checker,
        url_agent,
        image_agent,
        doc_reader,
        recipe_agent,
        tutor_agent,
    ],
    teams=[content_team],
    workflows=[research_pipeline],
    # Enable request tracing in the Agent OS UI
    tracing=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # reload=True enables hot-reload during development
    agent_os.serve(app="21_agent_os:app", reload=True)

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Agent OS features:

1. Chat interface
   Talk to any agent through a web UI at os.agno.com

2. Session management
   Browse conversation history, switch between sessions

3. Tracing
   See every LLM call, tool invocation, and knowledge search

4. Knowledge management
   View and manage documents in your knowledge bases

5. Custom endpoints
   app = agent_os.get_app()
   @app.get("/custom")
   def custom_endpoint():
       return {"status": "ok"}

For production deployment:
- Use PostgreSQL instead of SQLite (see cookbook/06_storage/)
- Add authentication (see cookbook/05_agent_os/)
- Use a proper WSGI server (gunicorn, uvicorn workers)
"""
