# Tools Cookbook Testing Log

Testing tool examples in `cookbook/90_tools/`.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Date: 2026-01-15 (reviewed), 2026-01-14 (initial)

---

## Test Results by Category

### Core Tools

| File | Status | Notes |
|------|--------|-------|
| calculator_tools.py | PASS | Math operations with multiply tool |
| duckduckgo_tools.py | PASS | Web search tool works |
| file_tools.py | PASS | File search and save operations |
| custom_tools.py | PASS | All 7 return types (dict, list, generator, pydantic, dataclass, set, tuple) |
| yfinance_tools.py | PARTIAL | Tool works, API rate limited |

---

### mcp/

| File | Status | Notes |
|------|--------|-------|
| basic_mcp.py | SKIP | Requires Node.js/npx |
| parallel.py | SKIP | Requires MCP server setup |
| local_server/*.py | SKIP | Requires fastmcp |

---

### tool_decorator/

| File | Status | Notes |
|------|--------|-------|
| basic_tool.py | SKIP | Basic @tool decorator example |

---

### async/

| File | Status | Notes |
|------|--------|-------|
| custom_async_tools.py | SKIP | Async tool patterns |

---

## TESTING SUMMARY

**Overall Results:**
- **Total Examples:** ~200 (116 root-level + subfolders)
- **Tested:** 5 files
- **Passed:** 4
- **Partial:** 1 (yfinance API rate limited)
- **Failed:** 0
- **Skipped:** MCP examples (require Node.js), provider-specific tools

**Fixes Applied:**
1. Fixed CLAUDE.md path reference (`cookbook/14_tools/` -> `cookbook/90_tools/`)
2. Fixed TEST_LOG.md path reference
3. Fixed 9 additional files with path references in mcp/ subfolder
4. Fixed `pip install` -> `uv pip install` in 55 files (2026-01-15)
5. Fixed `gpt-4o-mini` -> `gpt-5.2` in 18 files (2026-01-15)
6. Fixed model IDs in 4 files (6 occurrences):
   - `webbrowser_tools.py` - 2x `gemini-2.0-flash` -> `gemini-3-flash-preview`
   - `todoist_tools.py` - 2x `gemini-2.0-flash-exp` -> `gemini-3-flash-preview`
   - `google_bigquery_tools.py` - 1x `gemini-2.0-flash` -> `gemini-3-flash-preview`
   - `whatsapp_tools.py` - 1x `gemini-2.0-flash` -> `gemini-3-flash-preview`
5. Removed emojis from 12 files:
   - `visualization_tools.py` - Removed chart emojis from print statements and docstring
   - `notion_tools.py` - Removed search emoji
   - `nano_banana_tools.py` - Removed checkmark emoji
   - `docker_tools.py` - Replaced emojis with `[ERROR]` label
   - `custom_tool_events.py` - Removed checkmark emoji
   - `apify_tools.py` - Removed exploration emojis
   - `models/gemini_video_generation.py` - Removed wrench emoji from docstring
   - `models/gemini_image_generation.py` - Removed wrench emoji from docstring
   - `mcp/pipedream_slack.py` - Removed speech emoji from docstring
   - `mcp/pipedream_google_calendar.py` - Removed calendar emoji from docstring
   - `mcp/pipedream_auth.py` - Removed lock emoji from docstring
   - `mcp/mcp_toolbox_demo/hotel_management_workflows.py` - Removed hotel/checkmark emojis

**Key Features Verified:**
- Calculator tools (multiply, add, etc.)
- Web search tools (DuckDuckGo)
- File tools (search, read, save)
- Custom tool return types (dict, list, generator, pydantic, dataclass, set, tuple)

**Skipped Due to Dependencies:**
- MCP tools (require Node.js, npx, fastmcp)
- Provider-specific tools (require API keys: OpenAI DALL-E, ElevenLabs, etc.)
- Cloud tools (AWS, GCP, etc.)

**Notes:**
- Largest tool collection (200+ examples)
- Most tools require specific API keys or services
- Core tool patterns (custom tools, calculator) work without external deps
- MCP (Model Context Protocol) is well-documented but requires Node.js setup
