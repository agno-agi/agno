"""
1. Install dependencies using: `pip install opencv-python google-geneai sqlalchemy`
2. Install ffmpeg `brew install ffmpeg`
2. Run the script using: `python cookbook/agent_concepts/video_to_shorts.py`
"""

import subprocess
from pathlib import Path

from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini
from agno.utils.log import logger

video_path = Path(__file__).parent.joinpath("sample_video.mp4")
output_dir = Path("tmp/shorts")

agent = Agent(
    name="Video2Shorts",
    description="Process videos and generate engaging shorts.",
    model=Gemini(id="gemini-2.0-flash-exp"),
    markdown=True,
    instructions=[
        "Analyze the provided video directly—do NOT reference or analyze any external sources or YouTube videos.",
        "Identify engaging moments that meet the specified criteria for short-form content.",
        """Provide your analysis in a **table format** with these columns:
   - Start Time | End Time | Description | Importance Score""",
        "Ensure all timestamps use MM:SS format and importance scores range from 1-10. ",
        "Focus only on segments between 15 and 60 seconds long.",
        "Base your analysis solely on the provided video content.",
        "Deliver actionable insights to improve the identified segments for short-form optimization.",
    ],
)

# 2. Multimodal Query for Video Analysis
query = """

You are an expert in video content creation, specializing in crafting engaging short-form content for platforms like YouTube Shorts and Instagram Reels. Your task is to analyze the provided video and identify segments that maximize viewer engagement.

For each video, you'll:

1. Identify key moments that will capture viewers' attention, focusing on:
   - High-energy sequences
   - Emotional peaks
   - Surprising or unexpected moments
   - Strong visual and audio elements
   - Clear narrative segments with compelling storytelling

2. Extract segments that work best for short-form content, considering:
   - Optimal length (strictly 15–60 seconds)
   - Natural start and end points that ensure smooth transitions
   - Engaging pacing that maintains viewer attention
   - Audio-visual harmony for an immersive experience
   - Vertical format compatibility and adjustments if necessary

3. Provide a detailed analysis of each segment, including:
   - Precise timestamps (Start Time | End Time in MM:SS format)
   - A clear description of why the segment would be engaging
   - Suggestions on how to enhance the segment for short-form content
   - An importance score (1-10) based on engagement potential

Your goal is to identify moments that are visually compelling, emotionally engaging, and perfectly optimized for short-form platforms.
"""

# 3. Generate Video Analysis
response = agent.run(query, videos=[Video(filepath=video_path)])

# 4. Create output directory
output_dir = Path(output_dir)
output_dir.mkdir(parents=True, exist_ok=True)


# 5. Extract and cut video segments - Optional
def extract_segments(response_text):
    import re

    segments_pattern = r"\|\s*(\d+:\d+)\s*\|\s*(\d+:\d+)\s*\|\s*(.*?)\s*\|\s*(\d+)\s*\|"
    segments: list[dict] = []

    for match in re.finditer(segments_pattern, str(response_text)):
        start_time = match.group(1)
        end_time = match.group(2)
        description = match.group(3)
        score = int(match.group(4))

        # Convert timestamps to seconds
        start_seconds = sum(x * int(t) for x, t in zip([60, 1], start_time.split(":")))
        end_seconds = sum(x * int(t) for x, t in zip([60, 1], end_time.split(":")))
        duration = end_seconds - start_seconds

        # Only process high-scoring segments
        if 15 <= duration <= 60 and score > 7:
            output_path = output_dir / f"short_{len(segments) + 1}.mp4"

            # FFmpeg command to cut video
            command = [
                "ffmpeg",
                "-ss",
                str(start_seconds),
                "-i",
                video_path,
                "-t",
                str(duration),
                "-vf",
                "scale=1080:1920,setsar=1:1",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-y",
                str(output_path),
            ]

            try:
                subprocess.run(command, check=True)
                segments.append(
                    {"path": output_path, "description": description, "score": score}
                )
            except subprocess.CalledProcessError:
                print(f"Failed to process segment: {start_time} - {end_time}")

    return segments


logger.debug(f"{response.content}")

# 6. Process segments
shorts = extract_segments(response.content)

# 7. Print results
print("\n--- Generated Shorts ---")
for short in shorts:
    print(f"Short at {short['path']}")
    print(f"Description: {short['description']}")
    print(f"Engagement Score: {short['score']}/10\n")
