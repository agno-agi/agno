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

agent.print_response("Take a quick test photo to verify the camera is working")

response = agent.get_last_run_output()
if response and response.images:
    save_base64_data(
        base64_data=str(response.images[0].content),
        output_path="tmp/captured_test_image.png",
    )

# Example 2: Capture a video
agent.print_response("Capture a 5 second webcam video")

response = agent.get_last_run_output()
if response and response.videos:
    save_base64_data(
        base64_data=str(response.videos[0].content),
        output_path="tmp/captured_test_video.mp4",
    )
