"""Example: Meeting Summarizer & Visualizer Agent

This script uses OpenAITools (transcribe_audio, generate_image, generate_speech)
to process a meeting recording, summarize it, visualize it, and create an audio summary.

Requires: pip install openai agno
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.openai import OpenAITools

input_audio_file: str = "./sample_meeting.mp3"

meeting_agent: Agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    tools=[OpenAITools()],
    description=dedent("""\
        You are an efficient Meeting Assistant AI.
        Your purpose is to process audio recordings of meetings, extract key information,
        create a visual representation, and provide an audio summary.
    """),
    instructions=dedent(f"""\
        Follow these steps precisely:
        1.  Receive the path to an audio file.
        2.  Use the `transcribe_audio` tool to get the text transcription.
        3.  Analyze the transcription and write a concise summary highlighting key discussion points, decisions, and action items.
        4.  Based *only* on the summary created in step 3, formulate a *specific and detailed* prompt for the `generate_image` tool. This prompt should aim to create an image that visually represents the *core topics, decisions, or action items* identified in the summary. Think of it as a visual overview of the summary's content.
        5.  Call the `generate_image` tool with the prompt from step 4, using `model_name='dall-e-3'` and `size='1024x1024'`.
        6.  Call the `generate_speech` tool using the text summary from step 3. This tool returns the ID of the generated audio artifact.
        7.  Present the final output clearly: first the text summary, then include the exact image URL string returned by the `generate_image` tool (and mention the image artifact is in the context), and finally mention that the audio summary was generated and added to the context (using the artifact ID returned in step 6).
        Do not add any conversational text before or after the final output structure.
    """),
    markdown=True,
    show_tool_calls=True,
)

meeting_agent.print_response(
    f"Please process the meeting recording located at: {input_audio_file}"
)
