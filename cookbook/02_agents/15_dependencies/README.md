# 15_dependencies

Dependency injection for agents. Inject configuration, user-specific data, or
runtime resources into the agent context, into tools, and into instructions
via template strings.

## Files

Numbered files form a progression from simplest to most advanced. The
unnumbered files are kept as alternative entry points.

| File | What it shows |
|------|---------------|
| `01_static_dependencies.py` | Plain dict values — config, feature flags, tenant settings |
| `02_callable_dependencies.py` | Sync callables resolved once per run |
| `03_async_dependencies.py` | Async resolvers awaited via `arun` / `aprint_response` |
| `04_template_strings_in_instructions.py` | `{key}` substitution into instructions and system messages |
| `05_run_level_overrides.py` | Class-level defaults vs `agent.run(dependencies=...)` precedence |
| `06_runtime_aware_dependencies.py` | Resolvers that read `agent` and `run_context` (e.g. `user_id`) |
| `07_dependencies_with_memory.py` | Personalised flow combining dependencies with persistent memory |
| `dependencies_in_context.py` | Original example: `add_dependencies_to_context=True` with HackerNews |
| `dependencies_in_tools.py` | Read `run_context.dependencies` from inside a tool |
| `dynamic_tools.py` | Return a list of tools from a callable factory |

## Prerequisites

- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks
  with `.venvs/demo/bin/python`.

## Run

```bash
.venvs/demo/bin/python cookbook/02_agents/15_dependencies/<file>.py
```
