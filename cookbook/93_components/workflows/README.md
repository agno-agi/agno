# Workflow Steps Serialization Cookbooks

Examples for saving and loading workflows with advanced step types.

## Files
- `save_conditional_steps.py` - Workflow with `Condition` steps and evaluator restoration via `Registry`.
- `save_custom_steps.py` - Workflow with custom executor functions restored via `Registry`.
- `save_loop_steps.py` - Workflow with `Loop` steps and end-condition restoration via `Registry`.
- `save_parallel_steps.py` - Workflow with `Parallel` steps.
- `save_router_steps.py` - Workflow with `Router` steps and selector restoration via `Registry`.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Start PostgreSQL if needed: `./cookbook/scripts/run_pgvector.sh`.
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
