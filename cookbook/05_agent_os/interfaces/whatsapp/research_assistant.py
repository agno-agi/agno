"""
Research Assistant
==================

A WhatsApp agent that researches topics and writes papers as PDF documents.

Uses WhatsApp interactive features (reply buttons) to clarify ambiguous
topics, and ``FileGenerationTools`` to deliver results as downloadable PDFs.

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  ANTHROPIC_API_KEY
  pip install reportlab
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.file_generation import FileGenerationTools
from agno.tools.websearch import WebSearchTools
from agno.tools.whatsapp import WhatsAppTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent_db = SqliteDb(db_file="tmp/research_assistant.db")

research_agent = Agent(
    name="Research Agent",
    model=Claude(id="claude-sonnet-4-6"),
    tools=[
        WhatsAppTools(
            enable_send_reply_buttons=True,
        ),
        WebSearchTools(),
        FileGenerationTools(),
    ],
    db=agent_db,
    instructions=[
        "You are a research assistant that writes short research papers on any topic.",
        "When the user sends a topic, first acknowledge the request and let them know "
        "you are researching.",
        "Use DuckDuckGo to search for reliable information on the topic. Perform 2-3 "
        "searches with different queries to gather comprehensive data.",
        "Write a well-structured research paper with these sections: "
        "Title, Abstract, Introduction, Main Findings, Analysis, and Conclusion. "
        "Include references where possible.",
        "Use generate_pdf_file to create the paper as a PDF document with a descriptive "
        "title and the full paper content.",
        "After generating the PDF, send a short summary message to the user describing "
        "what the paper covers.",
        "If the topic is unclear, ask the user to clarify using send_reply_buttons "
        "with suggested sub-topics.",
        "Keep conversational messages short. Put the detailed content in the PDF.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[research_agent],
    interfaces=[Whatsapp(agent=research_agent, send_user_number_to_context=True)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="research_assistant:app", reload=True)
