# Test Log: 23_skills

Tested on 2026-07-24 against Agno source commit
`45bfff9f2aa6ec11b7386c3cd3bf6d1141d005dc`.

The lesson was loaded from the rewrite worktree, its scripts were executed
directly, and its Agent was exercised through a real model-backed AgentOS run.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the standalone AgentOS on port `8893`, checked health
and discovery, then asked `gpt-5.5` to load and execute the local system-info
skill through the non-streaming Agent run API.

**Result:** `/health` returned `ok`; `/config` returned
`skills-agent-os` and `skills-agent`. Run
`9c03f3c9-5ace-4e57-8844-7ac24f49969a` completed after recorded calls to
`get_skill_instructions` and `get_skill_script` with `execute=True`. The script
result had return code `0`, empty standard error, and JSON standard output for
host `Ios-MacBook-Pro.local`, OS `Darwin`, and Python `3.14.5`.

---

### sample_skills/system-info/scripts/get_system_info.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the script directly with the demo Python environment and
again through the executable skill tool.

**Result:** Direct execution exited `0` and printed one valid JSON document
containing architecture, UTC time, hostname, OS release, processor, Python
executable, and Python version. Skill-tool execution also exited `0`; its
standard output was the JSON consumed by the live AgentOS run.

---

### sample_skills/system-info/scripts/list_directory.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the script directly against the sample skill directory
and through the executable skill tool with `args=["."]`.

**Result:** Both executions exited `0` and printed valid JSON. The direct run
reported exactly the `scripts/` directory and `SKILL.md`, sorted with the
directory first.

---

## Validation

- Both direct scripts exited `0` and produced parseable JSON.
- `LocalSkills` validated and loaded `system-info`; `Skills` registered
  `get_skill_instructions`, `get_skill_reference`, and `get_skill_script`.
- The focused loader and skill-tool suites passed all 71 tests.
- Recursive pattern validation checked exactly 3 Python files with 0
  violations.
- Targeted Ruff format and check, Python compilation, inventory parity, local
  Markdown links, legacy deletion, and `git diff --check` passed.
