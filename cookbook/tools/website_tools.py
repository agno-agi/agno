from agno.agent import Agent
from pathlib import Path

from agno.knowledge.combined import CombinedKnowledgeBase
from agno.knowledge.csv import CSVKnowledgeBase
from agno.knowledge.pdf import PDFKnowledgeBase
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.knowledge.website import WebsiteKnowledgeBase
from agno.tools.website import WebsiteTools
from agno.vectordb.pgvector import PgVector


agent = Agent(tools=[WebsiteTools()], show_tool_calls=True)

agent.print_response(
    "Search web page: 'https://docs.agno.com/introduction'", markdown=True
)
