"""Run `uv pip install requests` to install dependencies."""

from agno.agent import Agent
from agno.models.response import FileType
from agno.tools.models_labs import ModelsLabTools
from agno.utils.media import download_audio
from agno.utils.pprint import pprint_run_response

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Create an image agent (PNG, using the Flux model)
image_agent = Agent(
    tools=[
        ModelsLabTools(file_type=FileType.PNG, model_id="flux", width=1024, height=1024)
    ],
    send_media_to_model=False,
)

# Create a video agent (set to make MP4)
video_agent = Agent(
    tools=[ModelsLabTools(file_type=FileType.MP4)], send_media_to_model=False
)

# Create audio agent (set to make WAV)
audio_agent = Agent(
    tools=[ModelsLabTools(file_type=FileType.WAV)], send_media_to_model=False
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Generate an image
    image_response = image_agent.run(
        "Generate an image of a beautiful sunset over the ocean"
    )
    pprint_run_response(image_response, markdown=True)

    # Generate a sound effect
    response = audio_agent.run("Generate a SFX of a ocean wave", markdown=True)
    pprint_run_response(response, markdown=True)

    if response.audio and response.audio[0].url:
        download_audio(
            url=response.audio[0].url,
            output_path="./tmp/nature.wav",
        )
