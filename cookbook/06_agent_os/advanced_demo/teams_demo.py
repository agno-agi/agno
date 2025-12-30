from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.yfinance import YFinanceTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url)

file_agent = Agent(
    name="File Upload Agent",
    id="file-upload-agent",
    role="Answer questions about the uploaded files",
    model=Claude(id="claude-3-7-sonnet-latest"),
    db=db,
    enable_user_memories=True,
    instructions=[
        "You are an AI agent that can analyze files.",
        "You are given a file and you need to answer questions about the file.",
    ],
    markdown=True,
)

video_agent = Agent(
    name="Video Understanding Agent",
    model=Gemini(id="gemini-2.0-flash"),
    id="video-understanding-agent",
    role="Answer questions about video files",
    db=db,
    enable_user_memories=True,
    add_history_to_context=True,
    add_datetime_to_context=True,
    markdown=True,
)

audio_agent = Agent(
    name="Audio Understanding Agent",
    id="audio-understanding-agent",
    role="Answer questions about audio files",
    model=OpenAIChat(id="gpt-4o-audio-preview"),
    db=db,
    enable_user_memories=True,
    add_history_to_context=True,
    add_datetime_to_context=True,
    markdown=True,
)

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    id="web_agent",
    instructions=[
        "You are an experienced web researcher and news analyst! 🔍",
    ],
    enable_user_memories=True,
    markdown=True,
    db=db,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    id="finance_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions=[
        "You are a skilled financial analyst with expertise in market data! 📊",
        "Follow these steps when analyzing financial data:",
        "Start with the latest stock price, trading volume, and daily range",
        "Present detailed analyst recommendations and consensus target prices",
        "Include key metrics: P/E ratio, market cap, 52-week range",
        "Analyze trading patterns and volume trends",
    ],
    enable_user_memories=True,
    markdown=True,
    db=db,
)

simple_agent = Agent(
    name="Simple Agent",
    role="Simple agent",
    id="simple_agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=["You are a simple agent"],
    enable_user_memories=True,
    db=db,
)

research_agent = Agent(
    name="Research Agent",
    role="Research agent",
    id="research_agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=["You are a research agent"],
    tools=[DuckDuckGoTools(), ExaTools()],
    enable_user_memories=True,
    db=db,
)

research_team = Team(
    name="Research Team",
    description="A team of agents that research the web",
    members=[research_agent, simple_agent],
    model=OpenAIChat(id="gpt-4o"),
    id="research_team",
    instructions=[
        "You are the lead researcher of a research team! 🔍",
    ],
    enable_user_memories=True,
    add_datetime_to_context=True,
    markdown=True,
    db=db,
)

multimodal_team = Team(
    name="Multimodal Team",
    description="A team of agents that can handle multiple modalities",
    members=[file_agent, audio_agent, video_agent],
    model=OpenAIChat(id="gpt-4o"),
    determine_input_for_members=False,
    respond_directly=True,
    id="multimodal_team",
    instructions=[
        "You are the lead editor of a prestigious financial news desk! 📰",
    ],
    enable_user_memories=True,
    db=db,
)
financial_news_team = Team(
    name="Financial News Team",
    description="A team of agents that search the web for financial news and analyze it.",
    members=[
        web_agent,
        finance_agent,
        research_agent,
        file_agent,
        audio_agent,
        video_agent,
    ],
    model=OpenAIChat(id="gpt-4o"),
    respond_directly=True,
    id="financial_news_team",
    instructions=[
        "You are the lead editor of a prestigious financial news desk! 📰",
        "If you are given a file send it to the file agent.",
        "If you are given an audio file send it to the audio agent.",
        "If you are given a video file send it to the video agent.",
        "Use USD as currency.",
        "If the user is just being conversational, you should respond directly WITHOUT forwarding a task to a member.",
    ],
    add_datetime_to_context=True,
    markdown=True,
    show_members_responses=True,
    db=db,
    enable_user_memories=True,
    expected_output="A good financial news report.",
)


# Setup our AgentOS app
agent_os = AgentOS(
    description="Example OS setup",
    agents=[
        simple_agent,
        web_agent,
        finance_agent,
        research_agent,
    ],
    teams=[research_team, multimodal_team, financial_news_team],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="teams_demo:app", reload=True)
