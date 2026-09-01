# Test Log - _25_tool_call_trajectories

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Schema-validated (query, tool call) pairs. Pulls the real JSON schemas of all 8 CalculatorTools functions and both DuckDuckGoTools functions via Function.process_entrypoint(), feeds the 10 schemas to a generator agent that writes 8 candidate pairs, then validates each pair in pure code against the real schema (known tool, JSON-parseable arguments, required params present, no unknown params, primitive types match). Valid rows go to data/generated/tool_call_sft.jsonl with schema_source provenance.

**Result:** Summary line: "wrote 8 rows ... kept 8, dropped 0". All 8 candidates passed validation in both runs today; the model reliably emits schema-exact arguments for these simple schemas (numbers as JSON numbers, integers for factorial/is_prime, optional max_results only when the query asks for it). The validator did not fire this run; kept/dropped can vary run to run.

---

### multi_turn_simulation.py

**Status:** PASS

**Description:** Two persona user-sim agents (dinner_host: 4 pizzas at 18.50 plus 12.75 fee split 5 ways; math_student: is 97 prime, then 12!/10!) talk to an assistant with tools=[CalculatorTools()] that actually executes calls. Up to 3 turns per persona; the full transcript is passed in each prompt; executed calls are read from RunOutput.tools (tool_name, tool_args, result). One row per conversation to data/generated/multi_turn_trajectories.jsonl.

**Result:** Summary line: "wrote 2 rows ... total 6 turns, 8 executed tool calls" (dinner_host 3 turns / 3 calls, math_student 3 turns / 5 calls). dinner_host executed multiply(4, 18.5) -> 74.0, add(74, 12.75) -> 86.75, divide(86.75, 5) -> 17.35, all correct. math_student executed is_prime(97), factorial(12), factorial(10), divide -> 132.0, plus a verification multiply(12, 11). Tool-call counts vary between runs (an earlier run gave 7 total: the assistant sometimes computes 12!/10! with fewer calls). The exporter strips the user-sim's DONE token before writing, so goal completion is not observable in the JSONL; the dinner_host trajectories end at the 3-turn cap with the final question still being answered, which is the expected shape for a multi-step goal under a hard turn cap.

---

### judge_filter.py

**Status:** PASS

**Description:** Imports PERSONAS, render_transcript, and run_conversation from multi_turn_simulation.py and re-runs the 2-persona simulation, so the file is standalone. A Gemini temperature=0 judge with output_schema TrajectoryVerdict(success, reason) reads each persona goal, transcript, and executed tool-call log, and only verified rollouts are written to data/generated/verified_trajectories.jsonl with the judge's reason under provenance.

**Result:** Summary line: "wrote 2 rows ... kept 2, dropped 0". Both trajectories were verified. Notable: in this run the assistant computed 12!/10! as a single multiply(12, 11) call (2 executed calls for math_student instead of 4-5 in earlier runs) and the judge correctly accepted the simplification, citing "which simplifies to 12 * 11 ... obtaining the correct result of 132". No failure case occurred today, so the drop path was exercised only by code inspection; with correct calculator arithmetic in context the assistant rarely fails these small goals.

---
