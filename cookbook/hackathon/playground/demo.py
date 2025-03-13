"""Run `pip install openai exa_py duckduckgo-search yfinance pypdf sqlalchemy 'fastapi[standard]' youtube-transcript-api python-docx agno` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage
from agno.tools.dalle import DalleTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.tools.youtube import YouTubeTools

agent_storage_file: str = "tmp/agents.db"
image_agent_storage_file: str = "tmp/image_agent.db"


simple_agent = Agent(
    name="Simple Agent",
    role="Answer basic questions",
    agent_id="simple-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=SqliteStorage(table_name="simple_agent", db_file=agent_storage_file),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
)

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    agent_id="web-agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "Break down the users request into 2-3 different searches.",
        "Always include sources",
    ],
    storage=SqliteStorage(table_name="web_agent", db_file=agent_storage_file),
    add_history_to_messages=True,
    num_history_responses=5,
    add_datetime_to_instructions=True,
    markdown=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    agent_id="finance-agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        )
    ],
    instructions=["Always use tables to display data"],
    storage=SqliteStorage(table_name="finance_agent", db_file=agent_storage_file),
    add_history_to_messages=True,
    num_history_responses=5,
    add_datetime_to_instructions=True,
    markdown=True,
)

image_agent = Agent(
    name="Image Agent",
    agent_id="image_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools(model="dall-e-3", size="1792x1024", quality="hd", style="vivid")],
    description="You are an AI agent that can generate images using DALL-E.",
    instructions=[
        "When the user asks you to create an image, use the `create_image` tool to create the image.",
        "Don't provide the URL of the image in the response. Only describe what image was generated.",
    ],
    markdown=True,
    debug_mode=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(table_name="image_agent", db_file=image_agent_storage_file),
)

youtube_agent = Agent(
    name="YouTube Agent",
    agent_id="youtube-agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[YouTubeTools()],
    description="You are a YouTube agent that has the special skill of understanding YouTube videos and answering questions about them.",
    instructions=[
        "Using a video URL, get the video data using the `get_youtube_video_data` tool and captions using the `get_youtube_video_data` tool.",
        "Using the data and captions, answer the user's question in an engaging and thoughtful manner. Focus on the most important details.",
        "If you cannot find the answer in the video, say so and ask the user to provide more details.",
        "Keep your answers concise and engaging.",
    ],
    add_history_to_messages=True,
    num_history_responses=5,
    show_tool_calls=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(table_name="youtube_agent", db_file=agent_storage_file),
    markdown=True,
)

app = Playground(
    agents=[
        simple_agent,
        web_agent,
        finance_agent,
        youtube_agent,
        image_agent,
    ]
).get_app()

if __name__ == "__main__":
    serve_playground_app("demo:app", reload=True)
