# Test Log: context_compression

> Updated: 2026-02-08 00:52:28 

## Pattern Check

**Status:** PASS

**Result:** Checked 2 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/context_compression. Violations: 0

---

### tool_call_compression.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/context_compression/tool_call_compression.py`.

**Result:** Exited with code 1 in 0.7s. Tail: File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/models/aws/bedrock.py", line 22, in <module> | raise ImportError("`boto3` not installed. Please install using `pip install boto3`") | ImportError: `boto3` not installed. Please install using `pip install boto3`

---

### tool_call_compression_with_manager.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/context_compression/tool_call_compression_with_manager.py`.

**Result:** Exited with code 1 in 0.48s. Tail: File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/models/aws/bedrock.py", line 22, in <module> | raise ImportError("`boto3` not installed. Please install using `pip install boto3`") | ImportError: `boto3` not installed. Please install using `pip install boto3`

---
