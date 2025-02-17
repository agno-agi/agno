from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.eleven_labs import ElevenLabsTools
from agno.tools.firecrawl import FirecrawlTools
from agno.utils.audio import write_audio_to_file

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
)

blog_to_podcast_agent.run(
    "Please convert this blog into a podcast: https://www.agno.com/blog/introducing-agno"
)

if blog_to_podcast_agent.run_response.audio is not None:
    for audio in blog_to_podcast_agent.run_response.audio:
        write_audio_to_file(audio.base64_audio, filename="tmp/podcast.wav")
