"""
pip install elevenlabs
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.eleven_labs import ElevenLabsTools

audio_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ElevenLabsTools(
            voice_id="21m00Tcm4TlvDq8ikWAM",
            model_id="eleven_multilingual_v2",
            target_directory="audio_generations",
        )
    ],
    description="You are an AI agent that can generate audio using the ElevenLabs API.",
    instructions=[
        "When the user asks you to generate audio, use the `generate_audio` tool to generate the audio.",
        "You'll generate the appropriate prompt to send to the tool to generate audio.",
        "You don't need to find the appropriate voice first, I already specified the voice to user."
        "Return the audio file name in your response. Don't convert it to markdown.",
        "The audio should be long and detailed.",
    ],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

audio_agent.print_response("Generate a very long audio of history of french revolution")

audio_agent.print_response("Generate a kick sound effect")
