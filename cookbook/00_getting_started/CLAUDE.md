# CLAUDE.md - Getting Started Cookbook

Instructions for Claude Code when testing the Getting Started cookbook.

---

## Quick Reference

**Test Environment:**
```bash
# Virtual environment (as per README)
source .getting-started/bin/activate

# Or use demo environment
.venvs/demo/bin/python

# API Key required
export GOOGLE_API_KEY=your-google-api-key
```

**Run a cookbook:**
```bash
python cookbook/00_getting_started/agent_with_tools.py
```

**Test results file:**
```
cookbook/00_getting_started/TEST_LOG.md
```

---

## Testing Workflow

### 1. Before Testing

Ensure environment is set up:
```bash
# Option A: Use README instructions
uv venv .getting-started --python 3.12
source .getting-started/bin/activate
uv pip install -r cookbook/00_getting_started/requirements.txt

# Option B: Use demo environment (already has dependencies)
source .venvs/demo/bin/activate
```

Set API key:
```bash
export GOOGLE_API_KEY=your-key
```

### 2. Running Tests

Run individual cookbooks:
```bash
python cookbook/00_getting_started/agent_with_tools.py
```

For long outputs:
```bash
python cookbook/00_getting_started/agent_with_tools.py 2>&1 | tail -100
```

### 3. Updating TEST_LOG.md

After each test, update `cookbook/00_getting_started/TEST_LOG.md` with:
- Test name and path
- Status: PASS or FAIL
- Brief description of what was tested
- Any notable observations or issues

---

## Cookbook Overview

| # | File | Dependencies | Notes |
|:--|:-----|:-------------|:------|
| 01 | `agent_with_tools.py` | Gemini, yfinance | Basic agent with tools |
| 02 | `agent_with_storage.py` | Gemini, yfinance, SQLite | Persistent conversations |
| 03 | `agent_search_over_knowledge.py` | Gemini, ChromaDb | Knowledge base + hybrid search |
| 04 | `custom_tool_for_self_learning.py` | Gemini, yfinance, ChromaDb | Custom tools |
| 05 | `agent_with_structured_output.py` | Gemini, yfinance | Pydantic output |
| 06 | `agent_with_typed_input_output.py` | Gemini, yfinance | Full type safety |
| 07 | `agent_with_memory.py` | Gemini, yfinance, SQLite | MemoryManager |
| 08 | `agent_with_state_management.py` | Gemini, yfinance, SQLite | Session state |
| 09 | `multi_agent_team.py` | Gemini, yfinance, duckduckgo | Multi-agent teams |
| 10 | `sequential_workflow.py` | Gemini, yfinance, duckduckgo | Workflows |
| 11 | `agent_with_guardrails.py` | Gemini, yfinance | Guardrails |
| 12 | `human_in_the_loop.py` | Gemini, yfinance, ChromaDb | Confirmation (interactive) |
| -- | `run.py` | All | Agent OS entrypoint |

---

## Key Dependencies

**Required:**
- `GOOGLE_API_KEY` - For Gemini model and embeddings
- `yfinance` - Stock data
- `chromadb` - Vector storage (local, no server)

**Optional (for specific cookbooks):**
- `duckduckgo-search` - For teams/workflows

**No external services required:**
- SQLite: Local file (`tmp/agents.db`)
- ChromaDb: Local directory (`tmp/chromadb`)

---

## Test Categories

### Basic (No DB)
- `agent_with_tools.py`
- `agent_with_structured_output.py`
- `agent_with_typed_input_output.py`
- `agent_with_guardrails.py`

### Storage (SQLite)
- `agent_with_storage.py`
- `agent_with_memory.py`
- `agent_with_state_management.py`

### Knowledge (ChromaDb)
- `agent_search_over_knowledge.py`
- `custom_tool_for_self_learning.py`
- `human_in_the_loop.py`

### Multi-Agent
- `multi_agent_team.py`
- `sequential_workflow.py`

### Interactive (requires user input)
- `human_in_the_loop.py` - Requires confirmation prompts

---

## Known Considerations

1. **Gemini API rate limits**: May need to wait between tests if hitting rate limits.

2. **Interactive tests**: `human_in_the_loop.py` requires user input - cannot be fully automated.

3. **Network dependent**: yfinance and DuckDuckGo require internet access.

4. **tmp/ directory**: Tests create files in `tmp/` - this is expected and can be cleaned up.


---

## Debugging

Enable debug output:
```python
import os
os.environ["AGNO_DEBUG"] = "true"
```

Check tmp files:
```bash
ls -la tmp/
# agents.db - SQLite database
# chromadb/ - Vector storage
```
