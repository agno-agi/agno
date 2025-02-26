"""🎤 Audio Input/Output with GPT-4 - Creating Voice Interactions with Agno

This example shows how to create an AI agent that can process audio input and generate
audio responses. You can use this agent for various voice-based interactions, from analyzing
speech content to generating natural-sounding responses.

Example audio interactions to try:
- Upload a recording of a conversation for analysis
- Have the agent respond to questions with voice output
- Process different languages and accents
- Analyze tone and emotion in speech

Run `pip install openai requests agno` to install dependencies.
"""

from textwrap import dedent

import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.openai import OpenAIChat
from agno.utils.audio import write_audio_to_file

# Create an AI Voice Interaction Agent
agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "wav"},
    ),
    description=dedent("""\
        You are an expert in audio processing and voice interaction, capable of understanding
        and analyzing spoken content while providing natural, engaging voice responses.
        You excel at comprehending context, emotion, and nuance in speech.\
    """),
    instructions=dedent("""\
        As a voice interaction specialist, follow these guidelines:
        1. Listen carefully to audio input to understand both content and context
        2. Provide clear, concise responses that address the main points
        3. When generating voice responses, maintain a natural, conversational tone
        4. Consider the speaker's tone and emotion in your analysis
        5. If the audio is unclear, ask for clarification

        Focus on creating engaging and helpful voice interactions!\
    """),
)

# Fetch the audio file and convert it to a base64 encoded string
url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
response = requests.get(url)
response.raise_for_status()

# Process the audio and get a response
agent.run(
    "What's in this recording? Please analyze the content and tone.",
    audio=[Audio(content=response.content, format="wav")],
)

# Save the audio response if available
if agent.run_response.response_audio is not None:
    write_audio_to_file(
        audio=agent.run_response.response_audio.content, filename="tmp/response.wav"
    )

# More example interactions to try:
"""
Try these voice interaction scenarios:
1. "Can you summarize the main points discussed in this recording?"
2. "What emotions or tone do you detect in the speaker's voice?"
3. "Please provide a detailed analysis of the speech patterns and clarity"
4. "Can you identify any background noises or audio quality issues?"
5. "What is the overall context and purpose of this recording?"

Note: You can use your own audio files by converting them to base64 format.
Example for using your own audio file:

with open('your_audio.wav', 'rb') as audio_file:
    audio_data = audio_file.read()
    agent.run("Analyze this audio", audio=[Audio(content=audio_data, format="wav")])
"""
