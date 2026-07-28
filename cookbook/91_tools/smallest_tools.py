"""
Smallest AI text-to-speech tools.

Requires the SMALLEST_API_KEY environment variable.
Get an API key at https://app.smallest.ai/dashboard (Developer -> API Keys).

Models:
- lightning_v3.1 (default): 12 languages, supports cloned voices
- lightning_v3.1_pro: premium voice pool, 29 languages

Language defaults to "en". For other language codes, see the model cards:
https://docs.smallest.ai/waves/model-cards/text-to-speech/lightning-v-3-1
https://docs.smallest.ai/waves/model-cards/text-to-speech/lightning-v-3-1-pro
"""

import base64
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.smallest import SmallestTools
from agno.utils.media import save_base64_data

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


audio_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        SmallestTools(
            voice_id="magnus",
            model="lightning_v3.1",
        )
    ],
    description="You are an AI agent that can generate audio using the Smallest AI API.",
    instructions=[
        dedent(
            """
            You have access to the Smallest AI toolkit:
            - Use the `text_to_speech` tool to convert text into natural voice audio.
            - Use the `get_voices` tool to list the available voices.
            Keep the audio prompt as defined by the user.
            """
        ),
    ],
    markdown=True,
)

# Premium voices: use the Lightning v3.1 Pro pool with a Pro voice
pro_audio_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        SmallestTools(
            voice_id="meher",
            model="lightning_v3.1_pro",
        )
    ],
    description="You are an AI agent that can generate premium audio using the Smallest AI API.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = audio_agent.run(
        "Generate a short audio welcoming listeners to a podcast about the history of aviation.",
    )

    if response.audio:
        print("Agent response:", response.content)
        base64_audio = base64.b64encode(response.audio[0].content).decode("utf-8")
        save_base64_data(base64_audio, "tmp/podcast_welcome.wav")

    # response2 = pro_audio_agent.run("Generate a short audio narrating a movie trailer.")
    # if response2.audio:
    #     print("Agent response:", response2.content)
    #     base64_audio = base64.b64encode(response2.audio[0].content).decode("utf-8")
    #     save_base64_data(base64_audio, "tmp/movie_trailer.wav")
