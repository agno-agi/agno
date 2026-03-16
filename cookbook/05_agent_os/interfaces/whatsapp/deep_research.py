"""
Deep Research Agent
===================

A multi-tool research agent that exercises many different tool types
to demonstrate WhatsApp's interactive capabilities.

Uses 7+ toolkits across web search, finance, news, academic papers,
and calculations. Also uses WhatsApp interactive features: reply buttons
for output format, reactions for completion, and mark-as-read.

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.arxiv import ArxivTools
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.file_generation import FileGenerationTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.newspaper4k import Newspaper4kTools
from agno.tools.whatsapp import WhatsAppTools
from agno.tools.wikipedia import WikipediaTools
from agno.tools.yfinance import YFinanceTools

agent_db = SqliteDb(db_file="tmp/deep_research.db")

deep_research_agent = Agent(
    name="Deep Research Agent",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[
        DuckDuckGoTools(),
        HackerNewsTools(),
        YFinanceTools(
            enable_stock_price=True,
            enable_company_info=True,
            enable_analyst_recommendations=True,
            enable_company_news=True,
        ),
        WikipediaTools(),
        ArxivTools(),
        CalculatorTools(),
        Newspaper4kTools(),
        FileGenerationTools(),
        WhatsAppTools(
            enable_send_reply_buttons=True,
            enable_send_reaction=True,
        ),
    ],
    instructions=[
        "You are a deep research assistant that gathers information from MANY sources.",
        "For every query, use AT LEAST 4 different tools to provide comprehensive answers.",
        "Always search the web AND check HackerNews AND Wikipedia for context.",
        "For finance questions, pull stock data, analyst recommendations, AND company news.",
        "For technical topics, also search Arxiv for relevant research papers.",
        "Use the calculator for any numerical analysis or comparisons.",
        "Use newspaper4k to read full articles when you find interesting URLs.",
        "Ask the user how they want the output delivered using send_reply_buttons "
        "with options: 'Text Summary' (id=text) and 'PDF Report' (id=pdf).",
        "If the user picks PDF, generate a structured report with sections using generate_pdf_file.",
        "After delivering the results, react to the original message with a checkmark emoji.",
        "Synthesize all findings into a well-structured summary with sections.",
    ],
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[deep_research_agent],
    interfaces=[Whatsapp(agent=deep_research_agent, send_user_number_to_context=True)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="deep_research:app", reload=True)
