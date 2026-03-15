"""
Agent OS - Deploy All Agents as a Web Service
===============================================
Deploy all agents, teams, and workflows from this guide as a single web service.

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
from db import gemini_agents_db

# Numbered filenames need importlib since Python can't import modules starting with digits
sys.path.insert(0, str(Path(__file__).parent))


def _import(module_name: str, attr: str):
    return getattr(importlib.import_module(module_name), attr)


chat_agent = _import("1_basic", "chat_agent")
finance_agent = _import("2_tools", "finance_agent")
critic_agent = _import("3_structured_output", "critic_agent")
news_agent = _import("4_search", "news_agent")
url_agent = _import("6_url_context", "url_agent")
image_agent = _import("8_image_input", "image_agent")
doc_reader = _import("13_pdf_input", "doc_reader")
recipe_agent = _import("17_knowledge", "recipe_agent")
tutor_agent = _import("18_memory", "tutor_agent")
content_team = _import("19_team", "content_team")
research_pipeline = _import("20_workflow", "research_pipeline")

agent_os = AgentOS(
    id="gemini-agent-os",
    agents=[
        chat_agent,
        finance_agent,
        critic_agent,
        news_agent,
        url_agent,
        image_agent,
        doc_reader,
        recipe_agent,
        tutor_agent,
    ],
    teams=[content_team],
    workflows=[research_pipeline],
    db=gemini_agents_db,
    tracing=True,
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="21_agent_os:app", reload=True)
