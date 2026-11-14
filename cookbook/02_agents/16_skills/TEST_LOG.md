# Test Log -- 16_skills

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### basic_skills.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates basic skills. Ran successfully and produced expected output.
**Result:** Completed successfully in 8s.

---

### mcp_skills.py

**Status:** PASS
**Tier:** untagged
**Description:** Module-level agent with `MCPSkills(command=...)`, which owns its MCP client and negotiates protocol revision 2026-07-28. On `aprint_response` it connected to `mcp_skills_server.py` over stdio and listed `review-server/code-review` and `review-server/git-workflow` without reading content. On demand the agent read `SKILL.md` and `references/style-guide.md`, each verified against the manifest digest and tagged `origin: mcp:review-server`. The model called `get_skill_script(..., execute=True)` and was refused, as MCP-served scripts are never executed. The server process exited when the run ended. Tested on 2026-10-12 with `.venv/bin/python` and `gpt-5.6-luna`.
**Result:** Completed successfully with a structured code review.

---

### mcp_skills_huggingface.py

**Status:** PASS
**Tier:** untagged
**Description:** Loads skills from Hugging Face's public MCP server with `MCPSkills(url="https://huggingface.co/mcp")`, no credentials. The server negotiated protocol revision 2026-07-28 and listed 25 skills. Asked how to estimate GGUF memory, the agent loaded `hf/hf-mem` and answered with the `hf-mem` command. A separate sweep of the same server verified all 25 `SKILL.md` files and all 133 supporting files against their manifest digests and frontmatter. Tested on 2026-10-12 with `.venv/bin/python` and `gpt-5.6-luna`.
**Result:** Completed successfully.

---

### mcp_skills_execution_gate.py

**Status:** PASS
**Tier:** untagged
**Description:** Agent with `ShellTools` and Hugging Face's MCP skills. The agent loaded `hf/hf-cli`, then called `run_shell_command` for `hf version`, which paused for confirmation. Answering "n" rejected it and the shell never ran; the agent reported it could not check. Answering "y" ran it (the `hf` CLI is not installed on the test machine, which the agent reported). Tested on 2026-10-14 with `.venv/bin/python` and `gpt-5.6-luna`.
**Result:** Both the reject and the approve paths completed as expected.

---
