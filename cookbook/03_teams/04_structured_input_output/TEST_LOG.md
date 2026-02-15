# Test Log: cookbook/03_teams/04_structured_input_output


## Pattern Check

**Status:** PASS

**Result:** Checked 11 file(s). Violations: 0

---

### expected_output.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/04_structured_input_output/expected_output.py`.

**Result:** Executed successfully.

---

### input_formats.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/04_structured_input_output/input_formats.py`.

**Result:** Executed successfully.

---

### input_schema.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### json_schema_output.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/json_schema_output.py", line 69, in <module>
    assert isinstance(response.content, dict)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---

### output_model.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/04_structured_input_output/output_model.py`.

**Result:** Executed successfully.

---

### output_schema_override.py

**Status:** FAIL

**Description:** Validation issue: style, runtime

**Result:** Style: code_before_first_section_banner | Run: ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/output_schema_override.py", line 107, in <module>
    assert isinstance(response.content, PersonSchema)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---

### parser_model.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### pydantic_input.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### pydantic_output.py

**Status:** FAIL

**Description:** Validation issue: style, runtime

**Result:** Style: code_before_first_section_banner | Run: ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/pydantic_output.py", line 69, in <module>
    assert isinstance(response.content, StockReport)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---

### response_as_variable.py

**Status:** FAIL

**Description:** Validation issue: style, runtime

**Result:** Style: code_before_first_section_banner | Run: ==================================================
STOCK PRICE ANALYSIS
==================================================
ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/response_as_variable.py", line 91, in <module>
    assert isinstance(stock_response.content, StockAnalysis)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---

### structured_output_streaming.py

**Status:** FAIL

**Description:** Validation issue: style, runtime

**Result:** Style: code_before_first_section_banner | Run: ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/structured_output_streaming.py", line 115, in <module>
    assert isinstance(run_response.content, StockReport)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---
