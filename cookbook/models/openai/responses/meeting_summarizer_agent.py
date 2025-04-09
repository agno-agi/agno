"""Example: Meeting Summarizer & Visualizer Agent

This script uses OpenAITools (transcribe_audio, generate_image, generate_speech)
to process a meeting recording, summarize it, visualize it, and create an audio summary.

Requires: pip install openai agno
Input: Update input_audio_file variable below.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.openai import OpenAITools

input_audio_file: str = "./sample_meeting.mp3"
output_summary_audio_file: str = "meeting_summary_audio.mp3"

openai_tools: OpenAITools = OpenAITools()

# Create the Meeting Summarizer Agent
meeting_agent: Agent = Agent(
    model=OpenAIChat(id="gpt-4o", temperature=0.5),
    tools=[openai_tools],
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
        5.  Call the `generate_image` tool with the prompt from step 4. Let's call the output image URL `image_url`.
        6.  Download the image from `image_url` and save it locally as 'meeting_summary_image.png' in the current directory. If you cannot directly save the image, proceed to the next step but note the URL.
        7.  Call the `generate_speech` tool using the text summary from step 3 as input, saving the audio to '{output_summary_audio_file}'.
        8.  Present the final output clearly: first the text summary, then the generated image URL (and mention if it was saved locally as 'meeting_summary_image.png'), and finally mention that the audio summary is saved to '{output_summary_audio_file}'.
        Do not add any conversational text before or after the final output structure.
    """),
    markdown=True,
    show_tool_calls=True,
)

# Define the user request
user_request: str = (
    f"Please process the meeting recording located at: {input_audio_file}"
)

# Print guidance
print(f"--- Meeting Summarizer & Visualizer Agent ---")
print(f"Processing audio file: {input_audio_file}")
print(f"Expecting audio summary output at: {output_summary_audio_file}")
print("Running agent...")
print("-------------------------------------------")

meeting_agent.print_response(user_request)
