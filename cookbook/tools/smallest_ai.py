"""
SmallestAI Tools for text-to-speech synthesis.

Prerequisites:
- Set the environment variable `SMALLEST_API_KEY` with your SmallestAI API key.
  You can obtain an API key from the SmallestAI website: https://waves.smallest.ai/
- Install the SmallestAI package: `pip install smallestai`

SmallestAI provides high-quality text-to-speech synthesis with multiple voices and models.
It supports both English and Hindi languages, various accents, and custom voice cloning.
"""

from dotenv import load_dotenv
import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.smallest_ai import SmallestAITools

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SMALLEST_API_KEY = os.getenv("SMALLEST_API_KEY")

# Example 1: Basic agent with default settings
audio_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SmallestAITools(
            voice_id="emily",  # Default American English female voice
            model="lightning",
            target_directory="audio_generations",
            sample_rate=24000,
            speed=1.0,
        )
    ],
    description="You are an AI agent that can generate audio using the SmallestAI API.",
    instructions=[
        "When the user asks you to generate audio, use the `text_to_speech` tool to generate the audio.",
        "You'll generate the appropriate prompt to send to the tool to generate audio.",
        "Return the audio file name in your response.",
        "The audio should be detailed and natural-sounding.",
    ],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

# Generate basic audio content
audio_agent.print_response(
    "Generate an audio talking about why every travel enthusiasts should visit India."
)


# Example 2: Agent for multilingual content (both Hindi and English)
multilingual_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SmallestAITools(
            voice_id="diya",  # Hindi-English bilingual voice (Indian accent)
            model="lightning",
            target_directory="audio_generations",
            sample_rate=24000,
            speed=1.0,
        )
    ],
    description="You are an AI agent that can generate audio in Hindi and English.",
    instructions=[
        "You can create audio content in both Hindi and English languages.",
        "When the user requests content, use the text_to_speech tool.",
        "The audio should be detailed and should sound realistic.",
    ],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

# Generate multilingual content (this generates two audio files in hindi and english)
multilingual_agent.print_response(
    "Generate an audio about Varun Mayya and what he is up to in both English and Hindi"
)

# Example 3: Agent with larger model and different voice
advanced_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SmallestAITools(
            voice_id="george",  # American male voice good for narratives and entertainment
            model="lightning-large",  # Enhanced model with more features
            target_directory="audio_generations",
            sample_rate=24000,
            speed=1.0,
            consistency=0.4,
            similarity=0.3,
            enhancement=1,
        )
    ],
    description="You are an AI agent that can generate high-quality narration.",
    instructions=[
        "You specialize in creating professional-quality audio narrations.",
        "When the user requests audio, use the text_to_speech tool with appropriate parameters.",
        "When using the lightning-large model, always include all the parameters data provided in SmallestAITools,"
        "for eg: enhancement, similarity, etc."
        "You have access to an enhanced TTS model that produces extremely high-quality speech.",
    ],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

# Generate enhanced quality audio
advanced_agent.print_response("Create a narration for a nature documentary about coral reefs")
