# Workflow Steps Serialization Cookbooks

Examples for saving and loading workflows with advanced step types.

## Files
- `save_conditional_steps.py` - Workflow with `Condition` steps and evaluator restoration via `Registry`.
- `save_custom_steps.py` - Workflow with custom executor functions restored via `Registry`.
- `save_loop_steps.py` - Workflow with `Loop` steps and end-condition restoration via `Registry`.
- `save_parallel_steps.py` - Workflow with `Parallel` steps.
- `save_router_steps.py` - Workflow with `Router` steps and selector restoration via `Registry`.

## HITL (Human-in-the-Loop) Config Files
- `save_hitl_confirmation_steps.py` - Workflow with step-level confirmation that round-trips through save/load.
- `save_hitl_user_input_steps.py` - Workflow that collects structured user input, with schema round-tripping through save/load.
- `save_hitl_condition_loop_router.py` - HITL config on `Condition`, `Loop`, and `Router` components with save/load verification.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Start PostgreSQL if needed: `./cookbook/scripts/run_pgvector.sh`.
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
