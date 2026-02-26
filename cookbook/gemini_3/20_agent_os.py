"""
20. Agent OS -- Deploy on Agent OS
===================================
All agents and teams from steps 1-19 deployed as a web service.
Agent OS provides a web interface for interacting with your agents.

How to Use
----------
1. Start the server:
   python cookbook/gemini_3/20_agent_os.py

2. Visit https://os.agno.com in your browser

3. Add your local endpoint: http://localhost:7777

4. Select any agent or team and start chatting

Prerequisites
-------------
- GOOGLE_API_KEY environment variable set
"""

import importlib
import sys
from pathlib import Path

from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Import agents from numbered files (Python can't import modules starting
# with digits directly, so we use importlib)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))


def _import(module_name: str, attr: str):
    return getattr(importlib.import_module(module_name), attr)


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
    tracing=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="20_agent_os:app", reload=True)
