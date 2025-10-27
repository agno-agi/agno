"""Run `pip install requests` to install dependencies."""

from pathlib import Path
from agno.agent import Agent
from agno.models.response import FileType
from agno.tools.models_labs import ModelsLabTools
from agno.utils.media import download_audio
from agno.utils.pprint import pprint_run_response

# Create a video agent (set to make MP4)
agent = Agent(tools=[ModelsLabTools(file_type=FileType.MP4)])

agent.print_response(
    "Generate a video of a beautiful sunset over the ocean", markdown=True
)

# Create audio agent (set to make WAV)
agent = Agent(tools=[ModelsLabTools(file_type=FileType.WAV)])
response = agent.run(
    "Generate a SFX of a ocean wave", markdown=True
)
pprint_run_response(response, markdown=True)

if response.audio and response.audio[0].url:
    download_audio(
        url=response.audio[0].url,
        output_path=str(Path(__file__).parent.joinpath("tmp/nature.wav")),
    )

