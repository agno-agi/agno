# Tools in code

Toolkits passed to `CodeMode(tools=[...])` bind into the kernel as handles instead of appearing in the model's tool schema. The handle name is the toolkit's name with a trailing `_tools` stripped, so `InventoryTools(name="inventory_tools")` becomes `inventory`.

Every bound function is awaitable regardless of whether the underlying entrypoint is sync, so the model never has to know which is which. Calls go through the tool's own Agno call path, so the tool's `tool_hooks` (sync and async), pre/post hooks and result caching apply. Hooks attached by the agent (`Agent(tool_hooks=[...])`) wrap the `execute` cell as a whole rather than each bridged call inside it, and `tool_call_limit` counts that cell as one call.

A tool that would pause the run — `requires_confirmation`, `requires_user_input`, `external_execution`, or any `@approval` — is refused inside the kernel with a message telling the model to ask for it as a regular tool call. A cell cannot pause an agent run, so the call must not happen at all.

Toolkits that manage their own connections — anything with `_requires_connect`, plus `MCPTools` — are connected when the run starts and closed when it ends, the same as toolkits attached directly to the agent. A toolkit whose `connect()` is async is connected on the first cell of the run, because agno connects toolkits from a synchronous frame; a toolkit already opened by hand (`async with MCPTools(...)`) is left alone. Functions a toolkit registers while connecting are bound too, so an MCP server's tools are callable from a cell. Async tool calls are awaited on the agent's own event loop, so a toolkit whose transport lives there — an MCP `ClientSession`, an `httpx` client, an `asyncpg` pool — works from a cell.

A tool name is not a Python name. An MCP server may call a tool `get-forecast`, which no expression in a cell can reference, so it binds as `get_forecast` and its docstring records the tool's own name. The tool is still called by its real name over the wire, so logs, hooks and caching are unaffected.

- `basic.py` — a toolkit bound into the kernel; the agent loops its calls in one cell instead of one tool call per part.
- `with_filesystem.py` — `FileSystem.tools()` as the `filesystem` handle: compute in the kernel, write durable notes to the database in the same cell.

A toolkit that fails to bind is replaced by an object whose every attribute access raises a descriptive `RuntimeError` naming the toolkit and the original error — never a `NameError`.
