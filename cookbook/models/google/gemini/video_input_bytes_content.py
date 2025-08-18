import requests
from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    markdown=True,
)

url = "https://videos.pexels.com/video-files/5752729/5752729-uhd_2560_1440_30fps.mp4"

# Download the video file from the URL as bytes
response = requests.get(url)
video_content = response.content

agent.print_response(
    "Tell me about this video",
    videos=[Video(content=video_content)],
)
