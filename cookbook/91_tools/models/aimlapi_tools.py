"""Run `uv pip install agno` to install dependencies.

AIMLAPITools gives an agent image, video, speech and transcription models from
AI/ML API (https://aimlapi.com) behind one key. Each capability is a separate
tool with its own model, so an agent can be handed only the ones it needs.

Set AIMLAPI_API_KEY, or pass api_key=... to the toolkit.

Example prompts to try:
- "Generate an image of a lighthouse in a storm"
- "Read this sentence aloud: The quick brown fox jumps over the lazy dog"
- "Make a short video of a paper boat drifting on a pond"
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.aimlapi import AIMLAPI
from agno.tools.models.aimlapi import AIMLAPITools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# The chat model and the media tools both run on AI/ML API.
agent = Agent(
    model=AIMLAPI(id="gpt-5.6-luna"),
    tools=[
        AIMLAPITools(
            image_model="openai/gpt-image-2",
            speech_model="openai/tts-1",
            speech_voice="alloy",
            # Video takes minutes; leave it off unless the agent should make clips.
            enable_generate_video=False,
        )
    ],
    # The chat model does not take audio or video back as input; the generated
    # media still comes out on the run output.
    send_media_to_model=False,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    Path("tmp").mkdir(exist_ok=True)

    # Example 1: image
    response = agent.run("Generate an image of a lighthouse in a storm")
    for image in response.images or []:
        path = Path("tmp") / f"aimlapi_{image.id}.png"
        path.write_bytes(image.content)
        print(f"Image saved to {path}")

    # Example 2: speech
    response = agent.run(
        "Read this aloud: The quick brown fox jumps over the lazy dog."
    )
    for audio in response.audio or []:
        path = Path("tmp") / f"aimlapi_{audio.id}.mp3"
        path.write_bytes(audio.content)
        print(f"Audio saved to {path}")

    # Example 3: transcription of the speech we just made
    for audio in response.audio or []:
        agent.print_response(f"Transcribe the audio file at tmp/aimlapi_{audio.id}.mp3")

    # Example 4: video, on an agent that has the tool enabled
    video_agent = Agent(
        model=AIMLAPI(id="gpt-5.6-luna"),
        tools=[
            AIMLAPITools(
                enable_generate_image=False,
                enable_generate_speech=False,
                enable_transcribe_audio=False,
                video_model="bytedance/seedance-2-5",
                video_duration=4,
                video_resolution="480p",
            )
        ],
        send_media_to_model=False,
        markdown=True,
    )
    response = video_agent.run(
        "Make a short video of a paper boat drifting on a calm pond"
    )
    for video in response.videos or []:
        path = Path("tmp") / f"aimlapi_{video.id}.mp4"
        path.write_bytes(video.content)
        print(f"Video saved to {path}")
