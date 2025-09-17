"""
OpenCV Tools - Computer Vision and Image Processing

This example demonstrates how to use OpenCVTools for computer vision tasks.
Shows enable_ flag patterns for selective function access.
OpenCVTools is a small tool (<6 functions) so it uses enable_ flags.

Steps to use OpenCV Tools:

1. Install OpenCV
   - Run: pip install opencv-python

2. Camera Permissions (macOS)
   - Go to System Settings > Privacy & Security > Camera
   - Enable camera access for Terminal or your IDE

3. Camera Permissions (Linux)
   - Ensure your user is in the video group: sudo usermod -a -G video $USER
   - Restart your session after adding to the group

4. Camera Permissions (Windows)
   - Go to Settings > Privacy > Camera
   - Enable "Allow apps to access your camera"

Note: Make sure your webcam is connected and not being used by other applications.
"""

import base64

from agno.agent import Agent
from agno.tools.opencv import OpenCVTools
from agno.utils.media import save_base64_data

# Example 1: All functions enabled with live preview (default behavior)
agent_full = Agent(
    name="Full OpenCV Agent",
    tools=[OpenCVTools(show_preview=True)],  # All functions enabled with preview
    description="You are a comprehensive computer vision specialist with all OpenCV capabilities.",
    instructions=[
        "Use all OpenCV tools for complete image processing and camera operations",
        "With live preview enabled, users can see real-time camera feed",
        "For images: show preview window, press 'c' to capture, 'q' to quit",
        "For videos: show live recording with countdown timer",
        "Provide detailed analysis of captured content",
    ],
    markdown=True,
)

# Example 2: Enable specific camera functions
agent_camera = Agent(
    name="Camera Specialist",
    tools=[
        OpenCVTools(
            show_preview=True,
            enable_capture_image=True,
            enable_capture_video=True,
        )
    ],
    description="You are a camera specialist focused on capturing images and videos.",
    instructions=[
        "Specialize in capturing images and videos from webcam",
        "Cannot perform advanced image processing or object detection",
        "Focus on high-quality image and video capture",
        "Provide clear instructions for camera operations",
    ],
    markdown=True,
)

# Example 3: Enable all functions using 'all=True' pattern
agent_comprehensive = Agent(
    name="Comprehensive Vision Agent",
    tools=[OpenCVTools(show_preview=True, all=True)],
    description="You are a full-featured computer vision expert with all capabilities enabled.",
    instructions=[
        "Perform advanced computer vision analysis and processing",
        "Use all available OpenCV functions for complex tasks",
        "Combine camera capture with real-time processing",
        "Provide comprehensive image analysis and insights",
    ],
    markdown=True,
)

# Example 4: Processing-focused agent (no camera capture)
agent_processor = Agent(
    name="Image Processor",
    tools=[
        OpenCVTools(
            show_preview=False,  # Disable live preview
            enable_capture_image=False,  # Disable camera capture
            enable_capture_video=False,  # Disable video capture
        )
    ],
    description="You are an image processing specialist focused on analyzing existing images.",
    instructions=[
        "Process and analyze existing images without camera operations",
        "Cannot capture new images or videos",
        "Focus on image enhancement, filtering, and analysis",
        "Provide detailed insights about image content and properties",
    ],
    markdown=True,
)

# Use the full agent for main examples
agent = agent_full

# Example 1: Interactive mode with live preview
print("Example 1: Interactive mode with live preview using full agent")

response = agent.run(
    "Take a quick test of camera, capture the photo and tell me what you see in the photo."
)

if response and response.images:
    print("Agent response:", response.content)
    image_base64 = base64.b64encode(response.images[0].content).decode("utf-8")
    save_base64_data(image_base64, "tmp/test.png")

# Example 2: Capture a video
response = agent.run("Capture a 5 second webcam video.")

if response and response.videos:
    save_base64_data(
        base64_data=str(response.videos[0].content),
        output_path="tmp/captured_test_video.mp4",
    )
