"""
1. Install dependencies: `pip install openai sqlalchemy 'fastapi[standard]' agno requests elevenlabs firecrawl-py`
2. Authenticate with agno: `agno setup`
3. Run the agent: `python cookbook/playground/multimodal_agent.py`

Docs on Agent UI: https://docs.agno.com/agent-ui
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage
from agno.tools.eleven_labs import ElevenLabsTools
from agno.tools.firecrawl import FirecrawlTools

agent_storage_file: str = "tmp/agents.db"
image_agent_storage_file: str = "tmp/image_agent.db"


blog_to_podcast_agent = Agent(
    name="Blog to Podcast Agent",
    agent_id="blog_to_podcast_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ElevenLabsTools(
            voice_id="JBFqnCBsd6RMkjVDRZzb",
            model_id="eleven_multilingual_v2",
            target_directory="audio_generations",
        ),
        FirecrawlTools(),
    ],
    description="You are an AI agent that can generate audio using the ElevenLabs API.",
    instructions=[
        "When the user provides a blog URL:",
        "1. Use FirecrawlTools to scrape the blog content",
        "2. Create a concise summary of the blog content that is NO MORE than 2000 characters long",
        "3. The summary should capture the main points while being engaging and conversational",
        "4. Use the ElevenLabsTools to convert the summary to audio",
        "You don't need to find the appropriate voice first, I already specified the voice to user",
        "Don't return file name or file url in your response or markdown just tell the audio was created successfully",
        "Ensure the summary is within the 2000 character limit to avoid ElevenLabs API limits",
    ],
    markdown=True,
    debug_mode=True,
    add_history_to_messages=True,
    storage=SqliteStorage(
        table_name="blog_to_podcast_agent", db_file=image_agent_storage_file
    ),
)

app = Playground(
    agents=[
        blog_to_podcast_agent,
    ]
).get_app(use_async=False)

if __name__ == "__main__":
    serve_playground_app("blog_to_podcast:app", reload=True)
