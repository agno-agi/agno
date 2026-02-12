# Test Log: structured_input_output

> Updated: 2026-02-12

## Pattern Check

**Status:** PASS

**Result:** Checked 10 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/structured_input_output. Violations: 0

---

### input_formats.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/input_formats.py`.

**Result:** Executed successfully. Duration: 42.58s. Tail: t detection, medical scans ┃ | ┃ - **NLP:** translation, summarization, chatbots                              ┃ | ┃ - **Speech/audio:** speech recognition, voice activity detection             ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---

### input_schema.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/input_schema.py`.

**Result:** Executed successfully. Duration: 125.01s. Tail: ctor/workspaces/agno/colombo/cookbook/03_teams/structured_input_output/input_schema.py:22: PydanticDeprecatedSince20: `min_items` is deprecated and will be removed, use `min_length` instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.12/migration/ |   research_topics: List[str] = Field(

---

### json_schema_output.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/json_schema_output.py`.

**Result:** Executed successfully. Duration: 14.1s. Tail:                            │ | │     "company_name": "NVIDIA Corporation",                                    │ | │     "analysis": "NVIDIA Corporation (NVDA) is currently trading at $192.73,… │ | │ }                                                                            │ | ╰──────────────────────────────────────────────────────────────────────────────╯

---

### output_model.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/output_model.py`.

**Result:** Executed successfully. Duration: 5.12s. Tail: ━━━━━━━━━━━━━━━━━━━━━━━━━━━┓ | ┃                                                                              ┃ | ┃ I'll now wait for the detailed itinerary from our Itinerary Planner.         ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---

### output_schema_override.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/output_schema_override.py`.

**Result:** Executed successfully. Duration: 124.14s. Tail:  DEBUG ------------- OpenAI Async Response Stream End -------------               | DEBUG Added RunOutput to Team Session                                            | DEBUG **** Team Run End: 5295ff6f-207b-443f-986a-6104a9a97041 ****               | BookSchema(title='Pride and Prejudice', author='Jane Austen', year=1813) | Schema after override: PersonSchema

---

### parser_model.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/parser_model.py`.

**Result:** Executed successfully. Duration: 23.36s. Tail: ong Trail Ridge Road', | │   │   'Guided ranger programs offering deeper insights into local ecology' | │   ], | │   difficulty_rating=3, | │   estimated_days=7, | │   special_permits_needed=[ | │   │   'Wilderness permits for overnight backcountry hikes (if applicable)', | │   │   'Advance reservations for popular facilities during peak seasons' | │   ] | )

---

### pydantic_input.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/pydantic_input.py`.

**Result:** Executed successfully. Duration: 35.23s. Tail: ibuted systems             ┃ | ┃ implementations. Enjoy exploring these posts for deeper understanding and    ┃ | ┃ practical strategies!                                                        ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---

### pydantic_output.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/pydantic_output.py`.

**Result:** Executed successfully. Duration: 8.72s. Tail:                            │ | │   "company_name": "NVIDIA Corporation",                                      │ | │   "analysis": "NVIDIA's stock price has been experiencing fluctuations rece… │ | │ }                                                                            │ | ╰──────────────────────────────────────────────────────────────────────────────╯

---

### response_as_variable.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/response_as_variable.py`.

**Result:** Executed successfully. Duration: 59.31s. Tail: OL METRICS  **********************               | DEBUG ------------------- OpenAI Response End --------------------               | DEBUG Added RunOutput to Team Session                                            | DEBUG **** Team Run End: 2e280926-3731-4146-8323-087827d70df8 ****               | Processed MSFT: StockAnalysis | Total responses processed: 3

---

### structured_output_streaming.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/structured_input_output/structured_output_streaming.py`.

**Result:** Executed successfully. Duration: 30.72s. Tail:                            │ | │   "company_name": "Apple Inc.",                                              │ | │   "analysis": "Apple Inc. is a leading technology company known globally fo… │ | │ }                                                                            │ | ╰──────────────────────────────────────────────────────────────────────────────╯

---
