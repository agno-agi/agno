"""
YOLO Object Detection Cookbook
-------------------------------
This cookbook demonstrates how to use YOLOTools with an Agno agent
to detect and count objects in local images using Ultralytics YOLO.

Prerequisites:
    pip install agno ultralytics openai

Set your OpenAI API key:
    export OPENAI_API_KEY=sk-...

Run this cookbook using:
    python cookbook/91_tools/yolo_tools.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yolo import YOLOTools

# Basic agent with default YOLOv11-nano weights
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YOLOTools()],
    markdown=True,
    show_tool_calls=True,
)

# Example 1: Detect all objects in an image
agent.print_response(
    "Detect all objects in the image at 'sample_images/street.jpg' and describe what you see.",
    stream=True,
)

# Example 2: Count a specific class
agent.print_response(
    "How many cars are there in 'sample_images/street.jpg'?",
    stream=True,
)

# Example 3: Multi-class count
agent.print_response(
    "Count all the people and vehicles separately in 'sample_images/street.jpg'.",
    stream=True,
)

# Example 4: Custom model and confidence threshold
precise_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YOLOTools(model="yolov8m.pt", conf_threshold=0.5)],
    markdown=True,
    show_tool_calls=True,
)

precise_agent.print_response(
    "List every object detected in 'sample_images/street.jpg' with exact bounding box coordinates.",
    stream=True,
)
