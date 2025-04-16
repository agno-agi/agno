"""Example: Meeting Summarizer & Visualizer Agent

This script uses OpenAITools (transcribe_audio, generate_image, generate_speech)
to process a meeting recording, summarize it, visualize it, and create an audio summary.

Requires: pip install openai agno
"""

from textwrap import dedent

import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.google import Gemini
from agno.tools.openai import OpenAITools
from agno.tools.reasoning import ReasoningTools

input_audio_url: str = (
    "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/sample_audio.mp3"
)

print("Downloading audio from URL...")
response = requests.get(input_audio_url, timeout=30)
audio_content = response.content

print("Done!")

meeting_agent: Agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    tools=[OpenAITools(), ReasoningTools()],
    description=dedent("""\
        You are an efficient Meeting Assistant AI.
        Your purpose is to process audio recordings of meetings, extract key information,
        create a visual representation, and provide an audio summary.
    """),
    instructions=dedent(f"""\
        Follow these steps precisely:
        1. Receive the path to an audio file.
        2. Use the `transcribe_audio` tool to get the text transcription.
        3. Analyze the transcription and write a concise summary highlighting key discussion points, decisions, and action items.
        4. Based *only* on the summary created in step 3, formulate a *specific and detailed* prompt for generating a visual representation of the meeting. This prompt should aim to create an image that visually represents the *core topics, decisions, or action items* identified in the summary. Think of it as a visual overview of the summary's content.
        5. Let's use model `dall-e-3` and save it to `meeting_summary.png`
        6. Present the final output clearly: first the text summary, then include the exact image URL string returned by the `generate_image` tool (and mention the image artifact is in the context), and finally mention that the audio summary was generated and added to the context (using the artifact ID returned in step 6).
    """),
    markdown=True,
    show_tool_calls=True,
)

meeting_agent.print_response(
    f"Please process the meeting recording.",
    audio=[Audio(content=audio_content)],
    debug=True,
)
