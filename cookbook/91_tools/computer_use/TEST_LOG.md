# Computer Use Test Log

## 2026-10-02

### computer_use_agent.py: web search and operator persona

**Status:** PASS for offline checks; NOT RUN live

**Description:** Kept the model at `gpt-5.6-luna` with `reasoning_effort="none"` (briefly tried
`gpt-6-luna`, then reverted), added `WebSearchTools` beside the
screen controls, and gave it a computer-operator persona. Loaded the agent without running it
and ran `voice_computer_use.py --check`.

**Result:** The agent loads with both toolkits, including `web_search` and
`search_news`, and the voice check passes. No model calls were made.

---

### computer_use_agent.py

**Status:** NOT RUN

**Description:** New example: a pyautogui `ScreenTools` toolkit (screenshot,
click, move, scroll, type, key presses, minimize, wait) with an OpenAI Responses
agent run through `print_response`. Scoped Ruff lint and formatting passed.

**Result:** Not executed. `pyautogui` is not installed in the development
environment, and a live run needs an OpenAI key and control of the desktop.

---
