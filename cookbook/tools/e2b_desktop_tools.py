"""
E2B Desktop Tools Example - Demonstrates how to use the E2B Desktop toolkit for interacting with a virtual desktop.

This example shows how to:
1. Set up authentication with E2B API
2. Initialize the E2BDesktopTools with proper configuration
3. Create an agent that can interact with a virtual desktop in a secure sandbox
4. Use the sandbox for automated desktop testing, screen capture, and more

Prerequisites:

1. Create an account and get your API key from E2B:
   - Visit https://e2b.dev/
   - Sign up for an account
   - Navigate to the Dashboard to get your API key

2. Install required packages:
   pip install e2b-desktop

3. Set environment variable:
   export E2B_API_KEY=your_api_key

Features:

- Take screenshots of the virtual desktop
- Control mouse movements and clicks
- Press keyboard keys and hotkeys
- Get information about the screen and cursor
- Access streaming video of the desktop
- Open files and URLs in the virtual desktop
- Run commands in the desktop environment
- Manage sandbox lifecycle

Usage:

Run this script with the E2B_API_KEY environment variable set to interact
with the E2B Desktop sandbox through natural language commands.
"""

import os
import sys
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.e2b_desktop import E2BDesktopTools

# Check if E2B_API_KEY is set
if not os.getenv("E2B_API_KEY"):
    print("ERROR: E2B_API_KEY environment variable is not set.")
    print("Please set it with: export E2B_API_KEY=your_api_key")
    sys.exit(1)

try:
    # You can specify custom resolution for the desktop if needed
    e2b_desktop_tools = E2BDesktopTools(
        timeout=600,  # 10 minutes timeout (in seconds)
        resolution=(1280, 720),  # Optional: custom resolution
        dpi=96,  # Optional: custom DPI
    )
    print("Successfully initialized E2B Desktop sandbox")

    agent = Agent(
        name="Desktop Automation Sandbox",
        agent_id="e2b-desktop-sandbox",
        model=OpenAIChat(id="gpt-4o"),
        tools=[e2b_desktop_tools],
        markdown=True,
        show_tool_calls=True,
        instructions=[
            "You are an expert at controlling a virtual desktop in a secure E2B sandbox environment.",
            "You can:",
            "1. Take screenshots (take_screenshot)",
            "2. Stream the desktop (start_stream, stop_stream, get_stream_url, get_video_stream_url)",
            "3. Control the mouse (left_click, right_click, double_click, middle_click, move_mouse, scroll, drag)",
            "4. Get cursor and screen information (get_cursor_position, get_screen_size)",
            "5. Type text and press keys (write, press_key, press_keys)",
            "6. Wait for animations or processes (wait)",
            "7. Open files and URLs (open)",
            "8. Run shell commands (run_command)",
            "9. Shutdown the sandbox when finished (shutdown_sandbox)",
            "",
            "Guidelines:",
            "- The sandbox provides a complete virtual desktop environment",
            "- For complex automation tasks, break them down into simple steps",
            "- Provide clear explanations of what you're doing at each step",
            "- When taking screenshots, explain what should be visible",
            "- Use wait() between actions that need time to complete",
            "- For keyboard shortcuts, use press_keys() with a list of keys, e.g., press_keys(['ctrl', 'c'])",
            "- For single key presses, use press_key() with a string, e.g., press_key('enter')",
            "- Handle errors gracefully",
            "- When finished with the session, remember to shut down the sandbox",
        ],
    )

    print("Starting interaction with E2B Desktop sandbox. Try these commands:")
    print("- Take a screenshot of the desktop")
    print("- Open Firefox and navigate to e2b.dev")
    print("- Type 'Hello world!' and press Enter")
    print("- Start streaming the desktop and get the URL")

    # Example interactions
    # agent.print_response("Take a screenshot of the desktop and save it to desktop.png")

    # More examples (uncomment to use)
    # agent.print_response("Move the mouse to position (500, 300) and then click")
    agent.print_response(
        "Open chrome and navigate to https://e2b.dev and give stream url"
    )
    # agent.print_response("Type 'Hello world!' and press Enter")
    # agent.print_response("Press Ctrl+C to copy selected text")
    # agent.print_response("Start streaming the desktop and give me the URL")
    # agent.print_response("Run the command 'ls -la' and show me the output")
    # agent.print_response("Get the current screen resolution")
    # agent.print_response("Shutdown the sandbox when finished")

except Exception as e:
    print(f"ERROR: Failed to initialize E2B Desktop sandbox: {e}")
    print("Please check your API key and internet connection.")
    sys.exit(1)
