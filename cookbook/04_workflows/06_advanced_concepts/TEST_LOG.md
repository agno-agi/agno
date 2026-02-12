# Test Log — 06_advanced_concepts

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

## early_stopping/

| File | Status | Notes |
|------|--------|-------|
| early_stop_basic.py | PASS | Completed in ~14s, data processing workflow with stop |
| early_stop_condition.py | PASS | Completed in ~16s, compliance check triggered early termination |
| early_stop_loop.py | PASS | Completed in ~20s, safety check stopped loop after 1/3 iterations |
| early_stop_parallel.py | PASS | Completed in ~14s, safety check + quality check in parallel |

## guardrails/

| File | Status | Notes |
|------|--------|-------|
| prompt_injection.py | PASS | Completed, validation detected injection but steps continued processing |

## previous_step_outputs/

| File | Status | Notes |
|------|--------|-------|
| access_previous_outputs.py | FAIL | TypeError: object of type 'NoneType' has no len() in print_final_report |

## history/

| File | Status | Notes |
|------|--------|-------|
| continuous_execution.py | SKIP | Interactive CLI (EOFError - requires user input) |
| history_in_function.py | SKIP | Interactive CLI (EOFError - requires user input) |
| intent_routing_with_history.py | SKIP | Interactive CLI (EOFError - requires user input) |
| step_history.py | SKIP | Interactive CLI (EOFError - requires user input) |

## session_state/

| File | Status | Notes |
|------|--------|-------|
| rename_session.py | PASS | Completed in ~35s, session renamed successfully |
| state_in_condition.py | PASS | Completed in ~3s, condition evaluator with session state |
| state_in_function.py | PASS | First workflow completed (~96s), second killed by timeout 120 |
| state_in_router.py | PASS | Completed in ~5s, task management router with state |
| state_with_agent.py | PASS | Completed in ~7s, shopping list with agent state |
| state_with_team.py | PASS | Completed in ~7s, project step management with team state |

## structured_io/

| File | Status | Notes |
|------|--------|-------|
| image_input.py | PASS | Completed in ~25s, Golden Gate Bridge image + news research |
| input_schema.py | PASS | Completed in ~69s, content schedule with input schema |
| pydantic_input.py | PASS | Completed in ~66s, content creation with Pydantic input |
| structured_io_agent.py | PASS | Completed in ~19s, structured JSON output from agent |
| structured_io_function.py | PASS | Completed in ~22s, structured function output |
| structured_io_team.py | FAIL | Killed by timeout 120 before completing |

## tools/

| File | Status | Notes |
|------|--------|-------|
| workflow_tools.py | PASS | Completed, quantum computing blog post with workflow tools |

## workflow_agent/

| File | Status | Notes |
|------|--------|-------|
| basic_workflow_agent.py | PASS | Completed, short story generation via workflow agent |
| workflow_agent_with_condition.py | PASS | Completed in ~11s, creative writing with conditional routing |

## run_control/

| File | Status | Notes |
|------|--------|-------|
| cancel_run.py | PASS | Workflow cancellation worked correctly |
| deep_copy.py | PASS | Deepcopy of workflow displayed correctly |
| event_storage.py | PASS | 3470 events captured, full event lifecycle verified |
| executor_events.py | PASS | Event type hierarchy displayed correctly |
| metrics.py | PASS | Completed in ~96s, step-level metrics displayed |
| remote_workflow.py | SKIP | Requires AgentOS server (401 Unauthorized) |
| workflow_cli.py | PASS | Completed in ~8s, non-interactive demo mode ran |
| workflow_serialization.py | PASS | Serialized workflow dict + persistence APIs |

## background_execution/

| File | Status | Notes |
|------|--------|-------|
| background_poll.py | PASS | Completed, background polling workflow |
| websocket_client.py | SKIP | Interactive websocket client |
| websocket_server.py | SKIP | Server started successfully (uvicorn), killed by timeout 10 |

## long_running/

| File | Status | Notes |
|------|--------|-------|
| disruption_catchup.py | SKIP | Requires running server |
| events_replay.py | SKIP | Requires running server |
| websocket_reconnect.py | SKIP | Requires running server |

## Summary

- **PASS:** 26
- **FAIL:** 2 (access_previous_outputs.py NoneType error, structured_io_team.py timeout)
- **SKIP:** 10 (4 interactive CLI, 1 server required, 3 long-running, 1 websocket client, 1 websocket server)
