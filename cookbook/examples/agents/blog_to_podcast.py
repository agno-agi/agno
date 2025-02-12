from agno.agent import Agent
from agno.tools.eleven_labs import ElevenLabsTools
# from agno.storage import SqliteAgentStorage
from agno.tools.firecrawl import FirecrawlTools
from agno.models.openai import OpenAIChat
from agno.tools.browserless import BrowserlessTools
from agno.playground import Playground, serve_playground_app


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
        # BrowserlessTools(),
        FirecrawlTools(),
    ],
    description="You are an AI agent that can generate audio using the ElevenLabs API.",
    instructions=[
        "When the user asks you to generate audio, use the `text_to_speech` tool to generate the audio.",
        "You'll generate the appropriate prompt to send to the tool to generate audio.",
        "You don't need to find the appropriate voice first, I already specified the voice to user."
        "Don't return file name or file url in your response or markdown just tell the audio was created successfully.",
        "The audio should be long and detailed.",
        "You can use the `browserless` tool to scrape the blog post and get the text content.",
    ],
    markdown=True,
    debug_mode=True,
    add_history_to_messages=True,
    # storage=SqliteAgentStorage(
    #     table_name="audio_agent", db_file=image_agent_storage_file
    # ),
)

app = Playground(
    agents=[
        blog_to_podcast_agent,
    ]
).get_app(use_async=False)

if __name__ == "__main__":
    serve_playground_app("blog_to_podcast:app", reload=True)