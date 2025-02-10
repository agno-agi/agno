import time
from pathlib import Path

from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini

model = Gemini(id="gemini-2.0-flash-exp")
agent = Agent(
    model=model,
    markdown=True,
)

# Please download a sample video file to test this Agent and upload using:

video_path = Path(__file__).parent.joinpath("sample_video.mp4")
video_file = None
remote_file_name = f"files/{video_path.stem.lower().replace('_', '')}"
try:
    video_file = model.get_client().files.get(name=remote_file_name)
except Exception as e:
    print(f"Error getting file {video_path.stem}: {e}")
    pass

if not video_file:
    try:
        video_file = model.get_client().files.upload(
            file=video_path,
            config=dict(name=video_path.stem, display_name=video_path.stem),
        )

        # Check whether the file is ready to be used.
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = model.get_client().files.get(name=video_file.name)

        print(f"Uploaded video: {video_file}")
    except Exception as e:
        print(f"Error uploading video: {e}")

agent.print_response(
    "Tell me about this video",
    videos=[Video(content=video_file)],
    stream=True,
)
