import os
from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.audio import write_audio_to_file
from agno.utils.streamlit import get_model_with_provider

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def generate_podcast_agent(
    model_id: str = "openai:gpt-4o",
    voice: str = "alloy",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Agent:
    """Create a Podcast Generator Agent"""

    os.makedirs("tmp", exist_ok=True)

    model = get_model_with_provider(model_id)

    # If using OpenAI, configure for audio output
    if model_id.startswith("openai:"):
        model = OpenAIChat(
            id=model_id.split("openai:")[1],
            modalities=["text", "audio"],
            audio={"voice": voice, "format": "wav"},
        )

    db = PostgresDb(
        db_url=db_url,
        session_table="sessions",
        db_schema="ai",
    )

    agent = Agent(
        name="Podcast Generator",
        model=model,
        db=db,
        id="podcast-generator",
        user_id=user_id,
        session_id=session_id,
        tools=[DuckDuckGoTools()],
        instructions=dedent("""
            You are a podcast scriptwriter specializing in concise and engaging narratives.
            Your task is to research a given topic and compose a compelling podcast script.

            ### Research Phase:
            - Use DuckDuckGo to gather the most recent and relevant information on the given topic
            - Prioritize trustworthy sources such as news sites, academic articles, or established publications
            - Identify key points, statistics, expert opinions, and interesting facts

            ### Scripting Phase:
            - Write a concise podcast script in a conversational tone
            - Begin with a strong hook to capture the listener's attention
            - Present key insights in an engaging, easy-to-follow manner
            - Include smooth transitions between ideas to maintain narrative flow
            - End with a closing remark that summarizes main takeaways

            ### Formatting Guidelines:
            - Use simple, engaging language suitable for audio
            - Keep the script under 300 words (around 2 minutes of audio)
            - Write in a natural, spoken format, avoiding overly formal or technical jargon
            - Structure: intro hook → main content → conclusion
            - No special formatting or markdown - just plain conversational text

            ### Example Output Structure:
            "Welcome to today's episode where we explore [TOPIC]. [Hook or interesting fact]
            
            [Main content with 2-3 key points, smooth transitions between ideas]
            
            [Conclusion with key takeaways and closing thoughts]
            
            Thanks for listening, and we'll see you next time!"
        """),
        markdown=True,
        debug_mode=True,
    )

    return agent


def generate_podcast(
    topic: str, voice: str = "alloy", model_id: str = "openai:gpt-4o"
) -> Optional[str]:
    """
    Generate a podcast script and convert it to audio.

    Args:
        topic (str): The topic of the podcast
        voice (str): Voice model for OpenAI TTS. Options: ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        model_id (str): Model to use for script generation

    Returns:
        str: Path to the generated audio file, or None if generation failed
    """
    try:
        # Create the podcast generator agent
        agent = generate_podcast_agent(model_id=model_id, voice=voice)

        # Generate the podcast script
        response = agent.run(f"Write a podcast script for the topic: {topic}")

        audio_file_path = "tmp/generated_podcast.wav"

        # If the model supports audio output and audio was generated
        if hasattr(response, "response_audio") and response.response_audio is not None:
            audio_content = response.response_audio.content

            if audio_content:
                write_audio_to_file(
                    audio=audio_content,
                    filename=audio_file_path,
                )
                return audio_file_path

        return None

    except Exception as e:
        print(f"Error generating podcast: {e}")
        return None
