# Test Log: structured_input_output

> Updated: 2026-02-08 00:52:28 

## Pattern Check

**Status:** PASS

**Result:** Checked 10 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/structured_input_output. Violations: 0

---

### input_formats.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/input_formats.py`.

**Result:** Completed successfully (exit 0) in 40.71s. Tail: ┃ models.                                                                      ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---

### input_schema.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/input_schema.py`.

**Result:** Timed out after 90.01s. Tail: DEBUG **********************  TOOL METRICS  ********************** | /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/structured_input_output/input_schema.py:23: PydanticDeprecatedSince20: `min_items` is deprecated and will be removed, use `min_length` instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.12/migration/ | research_topics: List[str] = Field(

---

### json_schema_output.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/json_schema_output.py`.

**Result:** Completed successfully (exit 0) in 6.41s. Tail: │     "analysis": "NVIDIA Corporation's recent performance has been driven by… │ | │ }                                                                            │ | ╰──────────────────────────────────────────────────────────────────────────────╯

---

### output_model.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/output_model.py`.

**Result:** Completed successfully (exit 0) in 4.66s. Tail: ┃ expert.                                                                      ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---

### output_schema_override.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/output_schema_override.py`.

**Result:** Completed successfully (exit 0) in 82.59s. Tail: DEBUG **** Team Run End: df6f7cef-be26-4e10-b620-56a87ae14b3b **** | BookSchema(title='Pride and Prejudice', author='Jane Austen', year=1813) | Schema after override: PersonSchema

---

### parser_model.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/parser_model.py`.

**Result:** Completed successfully (exit 0) in 32.43s. Tail: │   │   'Backcountry hiking permits (if applicable)' | │   ] | )

---

### pydantic_input.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/pydantic_input.py`.

**Result:** Completed successfully (exit 0) in 47.22s. Tail: ┃ targeted research.                                                           ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---

### pydantic_output.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/pydantic_output.py`.

**Result:** Completed successfully (exit 0) in 10.76s. Tail: │   "analysis": "NVIDIA's stock is currently facing some challenges in terms … │ | │ }                                                                            │ | ╰──────────────────────────────────────────────────────────────────────────────╯

---

### response_as_variable.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/response_as_variable.py`.

**Result:** Completed successfully (exit 0) in 55.22s. Tail: DEBUG **** Team Run End: 58e4bc9a-7fe2-4df7-9367-7bc93b4e8a97 **** | Processed MSFT: StockAnalysis | Total responses processed: 3

---

### structured_output_streaming.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/structured_output_streaming.py`.

**Result:** Completed successfully (exit 0) in 43.58s. Tail: │   "analysis": "Apple Inc. (AAPL) continues to be a key player in the global… │ | │ }                                                                            │ | ╰──────────────────────────────────────────────────────────────────────────────╯

---
