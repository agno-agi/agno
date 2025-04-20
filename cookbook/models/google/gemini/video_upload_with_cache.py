"""
In this example, we upload a very large video file to Google and then create a cache.

This greatly saves on tokens during normal prompting.
"""

from pathlib import Path
from time import sleep

import requests
from agno.agent import Agent
from agno.models.google import Gemini
from google import genai
from google.genai.types import CreateCachedContentConfig

client = genai.Client()

# Download video file
url = "https://storage.googleapis.com/generativeai-downloads/data/Sherlock_Jr_FullMovie.mp4"
path_to_video_file = Path(__file__).parent.joinpath("Sherlock_Jr_FullMovie.mp4")
if not path_to_video_file.exists():
    with path_to_video_file.open("wb") as wf:
        response = requests.get(url, stream=True)
        for chunk in response.iter_content(chunk_size=32768):
            wf.write(chunk)

# Upload the video using the Files API
video_file = client.files.upload(file=path_to_video_file)

# Wait for the file to finish processing
while video_file.state.name == "PROCESSING":
    print("Waiting for video to be processed.")
    sleep(2)
    video_file = client.files.get(name=video_file.name)

print(f"Video processing complete: {video_file.uri}")


# Create a cache with 5min TTL
cache = client.caches.create(
    model="gemini-2.0-flash-001",
    config=CreateCachedContentConfig(
        display_name="sherlock jr movie",  # used to identify the cache
        system_instruction=(
            "You are an expert video analyzer, and your job is to answer "
            "the user's query based on the video file you have access to."
        ),
        contents=[video_file],
        ttl="300s",
    ),
)


if __name__ == "__main__":
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-001", cached_content=cache.name),
        markdown=True,
        add_history_to_messages=True,
    )
    agent.print_response(
        "Introduce different characters in the movie by describing "
        "their personality, looks, and names. Also list the timestamps "
        "they were introduced for the first time.",  # No need to pass the video file
        stream=True,
    )

    print(agent.run_response.metrics)
