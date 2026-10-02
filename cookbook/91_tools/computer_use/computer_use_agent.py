"""
Computer Use Agent
==================
An agent that looks at your screen and drives the mouse and keyboard with
pyautogui. It takes a screenshot, decides what to do, acts, and takes another
screenshot to check the result. It can also search the web without opening a
browser.

Default task: minimize the current window, open Chrome, and go to agno.com.

    pip install pyautogui ddgs
    python cookbook/91_tools/computer_use/computer_use_agent.py
    python cookbook/91_tools/computer_use/computer_use_agent.py "Open Notepad and type hello"

Safety: this agent really clicks and types on your machine. Watch it while it
runs. Move the mouse into any screen corner to abort (pyautogui failsafe).
"""

import io
import sys
import time
from typing import List, Literal

import pyautogui
from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIResponses
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.tools.websearch import WebSearchTools

# Moving the mouse into a screen corner raises an exception and stops the run.
pyautogui.FAILSAFE = True
# A short pause after every pyautogui call gives the UI time to react.
pyautogui.PAUSE = 0.3

# Screenshots are downscaled to this width before the model sees them.
SCREENSHOT_WIDTH = 1280


# ---------------------------------------------------------------------------
# Screen Toolkit
# ---------------------------------------------------------------------------
class ScreenTools(Toolkit):
    """Look at the screen and control the mouse and keyboard.

    Coordinates are always in screenshot pixels. They are mapped back to real
    screen pixels, which also covers Windows display scaling.
    """

    def __init__(self, **kwargs):
        self.scale = 1.0
        super().__init__(
            name="screen",
            tools=[
                self.take_screenshot,
                self.click,
                self.move_mouse,
                self.scroll,
                self.type_text,
                self.press_keys,
                self.minimize_active_window,
                self.wait,
            ],
            **kwargs,
        )

    def _to_screen(self, x: int, y: int) -> tuple:
        width, height = pyautogui.size()
        screen_x = min(max(int(x * self.scale), 0), width - 1)
        screen_y = min(max(int(y * self.scale), 0), height - 1)
        return screen_x, screen_y

    def take_screenshot(self) -> ToolResult:
        """Capture the whole screen. Call this before acting and after each action to check the result.

        Returns:
            ToolResult: The screenshot and its size in pixels.
        """
        shot = pyautogui.screenshot()
        screen_width, _ = pyautogui.size()
        if shot.width > SCREENSHOT_WIDTH:
            height = round(shot.height * SCREENSHOT_WIDTH / shot.width)
            shot = shot.resize((SCREENSHOT_WIDTH, height))
        # Map screenshot pixels to pyautogui's coordinate space.
        self.scale = screen_width / shot.width
        buffer = io.BytesIO()
        shot.save(buffer, format="PNG")
        return ToolResult(
            content=f"Screenshot is {shot.width}x{shot.height} pixels. Use these coordinates for clicks.",
            images=[
                Image(
                    content=buffer.getvalue(),
                    format="png",
                    mime_type="image/png",
                    detail="high",
                )
            ],
        )

    def click(
        self,
        x: int,
        y: int,
        button: Literal["left", "right", "middle"] = "left",
        clicks: int = 1,
    ) -> str:
        """Click at a point on the latest screenshot.

        Args:
            x (int): Horizontal position in screenshot pixels.
            y (int): Vertical position in screenshot pixels.
            button (str): Mouse button to press.
            clicks (int): 1 for a single click, 2 for a double click.

        Returns:
            str: What was clicked.
        """
        screen_x, screen_y = self._to_screen(x, y)
        pyautogui.click(screen_x, screen_y, clicks=clicks, button=button)
        return f"Clicked {button} x{clicks} at ({x}, {y})."

    def move_mouse(self, x: int, y: int) -> str:
        """Move the mouse to a point on the latest screenshot without clicking.

        Args:
            x (int): Horizontal position in screenshot pixels.
            y (int): Vertical position in screenshot pixels.

        Returns:
            str: Where the mouse moved.
        """
        pyautogui.moveTo(*self._to_screen(x, y), duration=0.2)
        return f"Moved the mouse to ({x}, {y})."

    def scroll(self, amount: int) -> str:
        """Scroll the window under the mouse.

        Args:
            amount (int): Positive scrolls up, negative scrolls down.

        Returns:
            str: How far it scrolled.
        """
        pyautogui.scroll(amount)
        return f"Scrolled {amount}."

    def type_text(self, text: str) -> str:
        """Type text into the focused field, as if typed on the keyboard.

        Args:
            text (str): The text to type.

        Returns:
            str: What was typed.
        """
        pyautogui.write(text, interval=0.03)
        return f"Typed {text!r}."

    def press_keys(self, keys: List[str]) -> str:
        """Press one key, or a combination pressed together.

        Examples: ["enter"], ["ctrl", "l"], ["win"], ["alt", "tab"].

        Args:
            keys (List[str]): pyautogui key names. Several keys are pressed together.

        Returns:
            str: Which keys were pressed.
        """
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        return f"Pressed {'+'.join(keys)}."

    def minimize_active_window(self) -> str:
        """Minimize the window that currently has focus.

        Returns:
            str: Which window was minimized.
        """
        if sys.platform == "win32":
            window = pyautogui.getActiveWindow()
            if window is None:
                return "No active window to minimize."
            title = window.title
            window.minimize()
            return f"Minimized {title!r}."
        if sys.platform == "darwin":
            pyautogui.hotkey("command", "m")
            return "Pressed Command+M to minimize the active window."
        return "Minimizing windows is only supported on Windows and macOS."

    def wait(self, seconds: float = 1.0) -> str:
        """Wait for an app or page to finish loading.

        Args:
            seconds (float): How long to wait, up to 10 seconds.

        Returns:
            str: How long it waited.
        """
        seconds = min(max(seconds, 0.0), 10.0)
        time.sleep(seconds)
        return f"Waited {seconds} seconds."


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Computer Use Agent",
    # No hidden thinking between steps: each action follows the screenshot directly.
    model=OpenAIResponses(id="gpt-5.6-luna", reasoning_effort="none"),
    tools=[ScreenTools(), WebSearchTools()],
    description=(
        "You are a hands-on computer operator. You sit at this machine for the user and "
        "get things done on it the way a calm, experienced power user would: quickly, "
        "carefully, and without fuss."
    ),
    instructions=[
        # How you work
        "Treat the screen as the truth. Start every task with a screenshot, and never assume an action worked until a new screenshot shows it.",
        "Work in small, deliberate steps: look, act once, then look again before the next action.",
        "Before each action, say in a few words what you are doing, such as 'Opening Chrome.' Then call the tool. Keep it short; you may be speaking out loud.",
        "Choose the fastest reliable route. Look things up with web search instead of browsing for them, and use keyboard shortcuts such as Ctrl+L or Alt+Tab before hunting for buttons.",
        "To open an app on Windows, press the Windows key, type the app name, wait a moment, then press Enter.",
        "Give apps and pages time to load. If the screen has not changed yet, wait and check again rather than repeating the action.",
        # When things go wrong
        "If something does not go as expected, say what you see, then try one sensible alternative. If you are still stuck, stop and tell the user what is blocking you.",
        "Close or dismiss unexpected pop-ups and dialogs only when that is clearly safe; otherwise describe them and ask.",
        "If the request is ambiguous, ask one short question instead of guessing.",
        # Boundaries
        "Do only what the task asks, and leave everything else as you found it.",
        "Never type passwords, enter payment details, buy anything, send messages on the user's behalf, delete files, or close windows with unsaved work. Ask first if a task needs one of these.",
        # Finishing
        "When the task is done, confirm it from a final screenshot and say what you did in one or two sentences.",
    ],
    # Each action plus its check screenshot is two calls; this bounds a runaway loop.
    tool_call_limit=40,
    markdown=True,
    # Log each model call and tool call so you can follow what the agent does.
    debug_mode=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    task = (
        " ".join(sys.argv[1:])
        or "Minimize my current window, open Google Chrome, and go to agno.com by typing it into the address bar."
    )
    print("Starting in 3 seconds. Move the mouse into a screen corner to abort.")
    time.sleep(3)
    agent.print_response(task, stream=True)
