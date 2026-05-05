# CodingTools Test Log

### 01_basic_usage.py

**Status:** PASS

**Description:** Agent with 4 core tools (read_file, edit_file, write_file, run_shell) asked to list files and read README.md. Agent used run_shell to list directory and read_file to display the README with line numbers.

**Result:** Agent successfully used both tools, displayed directory listing and full README contents. Response completed in ~15s.

---

### 02_all_tools.py

**Status:** PASS

**Description:** Agent with all 7 tools (core + grep, find, ls) asked to find Python files and grep for imports. Agent used find with `**/*.py` glob, then grep with `--include='*.py'` and a regex pattern for import statements.

**Result:** Agent found 500+ Python files (hit the limit cap), then grep returned 118,442 import matches. Full output saved to temp file due to truncation. Agent summarized results clearly. Response completed in ~27s.

---
