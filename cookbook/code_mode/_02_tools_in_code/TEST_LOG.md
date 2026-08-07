# Test Log - _02_tools_in_code

Tested 2026-08-08 against `gpt-5.5` (OpenAIResponses), agno 3.0.0a1, ipykernel 7.3.0, on `.venvs/demo`.

### basic.py

**Status:** PASS

**Description:** `InventoryTools` (a 5-part stock table) bound into the kernel as the `inventory` handle. The agent was asked to look up every part's stock level in one cell and report which are out of stock plus the total.

**Result:** Response in 14.4s: "Out of stock: flange. Total inventory: 197 units." Both correct against the fixture (42+7+0+130+18 = 197, flange at 0). The model looped the bridged calls inside one cell rather than issuing five separate tool calls — the composition property the design exists for.

---

### with_filesystem.py

**Status:** PASS

**Description:** `FileSystem.tools()` composed into CodeMode as the `filesystem` handle over a SqliteDb. The agent was asked to compute mean and standard deviation in the kernel, then append a summary line to `stats/summary.md` through the filesystem handle.

**Result:** Response in 18.1s. The agent computed the statistics in the kernel and wrote the note through the bridged `append_file` call, then reported what it had written. Compute and durable write happened through one tool surface.
