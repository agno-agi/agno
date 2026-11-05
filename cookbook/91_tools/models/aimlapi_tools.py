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

import mimetypes
from pathlib import Path

from agno.agent import Agent
from agno.models.aimlapi import AIMLAPI
from agno.tools.models.aimlapi import AIMLAPITools

OUTPUT_DIR = Path("tmp")

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
            # Local files handed to transcribe_audio are read from here only.
            base_dir=OUTPUT_DIR,
            # Video takes minutes; leave it off unless the agent should make clips.
            enable_generate_video=False,
        )
    ],
    # The chat model does not take audio or video back as input; the generated
    # media still comes out on the run output.
    send_media_to_model=False,
    markdown=True,
)


def save(artifact, stem: str) -> Path:
    """Write a generated artifact next to the others, named by its media type."""
    extension = (
        mimetypes.guess_extension(artifact.mime_type or "") or f".{artifact.format}"
    )
    path = OUTPUT_DIR / f"{stem}_{artifact.id}{extension}"
    path.write_bytes(artifact.content)
    return path


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Example 1: image
    response = agent.run("Generate an image of a lighthouse in a storm")
    for image in response.images or []:
        print(f"Image saved to {save(image, 'aimlapi')}")

    # Example 2: speech
    response = agent.run(
        "Read this aloud: The quick brown fox jumps over the lazy dog."
    )
    saved_audio = [save(audio, "aimlapi") for audio in response.audio or []]
    for path in saved_audio:
        print(f"Audio saved to {path}")

    # Example 3: transcription of the speech we just made (path relative to base_dir)
    for path in saved_audio:
        agent.print_response(f"Transcribe the audio file {path.name}")

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
        print(f"Video saved to {save(video, 'aimlapi')}")
