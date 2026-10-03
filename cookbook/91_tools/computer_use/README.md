# Computer Use

An agent that sees your screen and drives the mouse and keyboard with
[pyautogui](https://pyautogui.readthedocs.io/). It loops: take a screenshot,
decide on one action, act, then take another screenshot to check the result.

## Run

```bash
pip install pyautogui ddgs
export OPENAI_API_KEY="..."
python cookbook/91_tools/computer_use/computer_use_agent.py
```

The default task minimizes the current window, opens Google Chrome, and goes to
agno.com. Pass your own task as arguments:

```bash
python cookbook/91_tools/computer_use/computer_use_agent.py "Open Notepad and type hello"
```

The script waits 3 seconds before starting. Because it minimizes "the current
window", the window it minimizes is usually the terminal you started it from.

## Tools

`ScreenTools` is defined in the example as a regular Agno `Toolkit`:

| Tool | What it does |
| --- | --- |
| `take_screenshot` | Returns the screen as an image the model can see |
| `click` / `move_mouse` | Mouse actions at screenshot coordinates |
| `scroll` | Scroll the window under the mouse |
| `type_text` | Type text into the focused field |
| `press_keys` | Press one key or a combination such as `["ctrl", "l"]` |
| `minimize_active_window` | Minimize the focused window (Windows and macOS) |
| `wait` | Pause up to 10 seconds while something loads |

Screenshots are downscaled to 1280 pixels wide before the model sees them. Click
coordinates are mapped back to real screen pixels, which also covers Windows
display scaling.

## Safety

This agent really clicks and types on your machine. Watch it while it runs.

- Move the mouse into any screen corner to abort (pyautogui failsafe).
- `tool_call_limit=40` bounds a runaway loop.
- The instructions forbid typing passwords, buying anything, or closing windows
  with unsaved work, but instructions are not a security boundary. Do not run it
  with sensitive apps open.

Every screenshot stays in the run's context, so long tasks get slower and use
more tokens.
