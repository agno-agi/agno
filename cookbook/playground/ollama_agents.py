"""Run `pip install ollama duckduckgo-search yfinance pypdf sqlalchemy 'fastapi[standard]' youtube-transcript-api agno` to install dependencies."""

from agno.agent import Agent
from agno.models.ollama import Ollama
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.tools.youtube import YouTubeTools

local_agent_storage_file: str = "tmp/local_agents.db"
common_instructions = [
    "If the user about you or your skills, tell them your name and role.",
]

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    agent_id="web-agent",
    model=Ollama(id="llama3.1:8b"),
    tools=[DuckDuckGoTools()],
    instructions=["Always include sources."] + common_instructions,
    storage=SqliteStorage(
        table_name="web_agent",
        db_file=local_agent_storage_file,
        auto_upgrade_schema=True,
    ),
    show_tool_calls=True,
    add_history_to_messages=True,
    num_history_responses=2,
    add_name_to_instructions=True,
    add_datetime_to_instructions=True,
    markdown=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    agent_id="finance-agent",
    model=Ollama(id="llama3.1:8b"),
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        )
    ],
    description="You are an investment analyst that researches stocks and helps users make informed decisions.",
    instructions=["Always use tables to display data"] + common_instructions,
    storage=SqliteStorage(
        table_name="finance_agent",
        db_file=local_agent_storage_file,
        auto_upgrade_schema=True,
    ),
    add_history_to_messages=True,
    num_history_responses=5,
    add_name_to_instructions=True,
    add_datetime_to_instructions=True,
    markdown=True,
)


youtube_agent = Agent(
    name="YouTube Agent",
    role="Understand YouTube videos and answer questions",
    agent_id="youtube-agent",
    model=Ollama(id="llama3.1:8b"),
    tools=[YouTubeTools()],
    description="You are a YouTube agent that has the special skill of understanding YouTube videos and answering questions about them.",
    instructions=[
        "Using a video URL, get the video data using the `get_youtube_video_data` tool and captions using the `get_youtube_video_data` tool.",
        "Using the data and captions, answer the user's question in an engaging and thoughtful manner. Focus on the most important details.",
        "If you cannot find the answer in the video, say so and ask the user to provide more details.",
        "Keep your answers concise and engaging.",
    ]
    + common_instructions,
    add_history_to_messages=True,
    num_history_responses=5,
    show_tool_calls=True,
    add_name_to_instructions=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="youtube_agent",
        db_file=local_agent_storage_file,
        auto_upgrade_schema=True,
    ),
    markdown=True,
)

app = Playground(agents=[web_agent, finance_agent, youtube_agent]).get_app()

if __name__ == "__main__":
    serve_playground_app("ollama_agents:app", reload=True)
