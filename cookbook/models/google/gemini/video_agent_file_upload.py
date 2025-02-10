import time
from pathlib import Path

from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini
from google.generativeai import get_file, upload_file

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    markdown=True,
)

# Please download "GreatRedSpot.mp4" using
# wget https://storage.googleapis.com/generativeai-downloads/images/GreatRedSpot.mp4
video_path = Path(__file__).parent.joinpath("GreatRedSpot.mp4")
video_file = upload_file(video_path)
# Check whether the file is ready to be used.
while video_file.state.name == "PROCESSING":
    print("Checking:", video_file.name)
    time.sleep(2)
    video_file = get_file(video_file.name)

print(f"Uploaded video: {video_file}")

agent.print_response(
    "Tell me about this video", videos=[Video(content=video_file)], stream=True
)
