"""
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

# Example 1: Agent with live preview enabled (interactive mode)
print("Example 1: Interactive mode with live preview")
agent = Agent(
    instructions=[
        "You can capture images and videos from the webcam using OpenCV tools",
        "With live preview enabled, users can see what they're capturing in real-time",
        "For images: show preview window, press 'c' to capture, 'q' to quit",
        "For videos: show live recording with countdown timer",
    ],
    tools=[OpenCVTools(show_preview=True)],  # Enable live preview
)

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
