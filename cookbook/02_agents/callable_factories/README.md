# Callable Factories

Resolve tools and team members at runtime using callable factories.

Instead of passing a static list, pass a **function** that returns the resource. The function is called at the start of each run and receives context via signature-based parameter injection (`agent`, `team`, `run_context`, `session_state`).

## Examples

- **[01_callable_tools.py](./01_callable_tools.py)** - Vary the toolset per user role (cached per user_id)
- **[02_session_state_tools.py](./02_session_state_tools.py)** - Use `session_state` directly as a parameter, with caching disabled
- **[03_team_callable_members.py](./03_team_callable_members.py)** - Assemble team members dynamically
