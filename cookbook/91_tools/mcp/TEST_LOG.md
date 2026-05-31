# Test Log

### Pending

**Status:** NOT RUN

**Description:** Tests for this cookbook directory have not been executed yet in this workspace.

**Result:** Add individual run results after executing examples.

---

### Bilig WorkPaper MCP

**Status:** PASS

**Command:** `uv run --with agno --with mcp --with openai python cookbook/91_tools/mcp/bilig_workpaper.py`

**Description:** Starts the published Bilig WorkPaper MCP server over stdio with
`@bilig/workpaper@latest`, creates a writable demo WorkPaper, edits `Inputs!B3`,
verifies recalculated formula readback, and verifies JSON persistence.

**Result:** Expected ARR changed from `60000` to `96000`, expected customers
changed to `8`, persistence was `True`, restored readback matched the edited
value, and the exported WorkPaper document was written.

---
