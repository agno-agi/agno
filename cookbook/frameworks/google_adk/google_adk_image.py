"""
Send an image to a Google ADK agent.

Gemini is multimodal, so images, audio, videos and files passed to run() go to
the model as native parts of the user message.

Requirements:
    pip install google-adk
    export GOOGLE_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/google_adk/google_adk_image.py
"""

from pathlib import Path

from agno.agents.google_adk import GoogleADKAgent
from agno.media import Image
from google.adk.agents import LlmAgent

adk_agent = LlmAgent(
    name="vision",
    model="gemini-3.7-flash",
    instruction="Describe images briefly and read out any amounts you see.",
)

agent = GoogleADKAgent(name="ADK Vision", agent=adk_agent)

image_path = (
    Path(__file__).resolve().parents[2]
    / "07_knowledge"
    / "testing_resources"
    / "restaurant_invoice.jpeg"
)

agent.print_response(
    "What is in this picture, and what is the total?",
    images=[Image(filepath=image_path)],
    stream=True,
)
