# Tools in code

Toolkits passed to `CodeMode(tools=[...])` bind into the kernel as handles instead of appearing in the model's tool schema. The handle name is the toolkit's name with a trailing `_tools` stripped, so `InventoryTools(name="inventory_tools")` becomes `inventory`.

Every bound function is awaitable regardless of whether the underlying entrypoint is sync, so the model never has to know which is which. Calls go through the normal Agno call path, so hooks, confirmation, and caching still apply.

- `basic.py` — a toolkit bound into the kernel; the agent loops its calls in one cell instead of one tool call per part.
- `with_filesystem.py` — `FileSystem.tools()` as the `filesystem` handle: compute in the kernel, write durable notes to the database in the same cell.

A toolkit that fails to bind is replaced by an object whose every attribute access raises a descriptive `RuntimeError` naming the toolkit and the original error — never a `NameError`.
