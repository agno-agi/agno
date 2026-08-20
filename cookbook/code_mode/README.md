# CodeMode

**CodeMode** gives the agent one programmable environment instead of a wide tool schema. The model writes Python; the code runs in an IPython kernel that lives as long as the session. Variables, imports, helper functions, and parsed tool results survive across turns. Every other toolkit you attach becomes a callable inside that kernel rather than a separate entry in the model's tool list, so a tool call is an `await` expression the model can bind to a variable, loop, and compose.

CodeMode caps what a cell can print, so the context holds conclusions and the kernel holds the data. Its sibling for ordinary tools is result offloading, `Agent(offload_tool_results=True)`, in [`../02_agents/22_result_offloading/`](../02_agents/22_result_offloading/).

Start with [`_01_basics/basic.py`](_01_basics/basic.py).

## Install

CodeMode needs an optional extra:

```bash
pip install 'agno[code-mode]'
```

## Layout

````
cookbook/code_mode/
├── README.md
├── _01_basics/                 # one tool, a live kernel
├── _02_tools_in_code/          # toolkits as awaitable handles
└── _03_persistence/            # state that survives the process
````

## Folders

- [`_01_basics/`](_01_basics/): the smallest working agent, and `%%bash` shell cells.
- [`_02_tools_in_code/`](_02_tools_in_code/): binding a toolkit into the kernel, and composing with the agent filesystem.
- [`_03_persistence/`](_03_persistence/): dill snapshots into AgentFS, and the developer-facing surface (`run` / `variables` / `value` / `shutdown`).

## Security

`execute` runs arbitrary Python and arbitrary shell with the permissions of the process running the agent. It is not a sandbox and does not pretend to be one: use a trusted operator or an isolated container. `allow_shell=False` strips the `%%bash` magic, but that is a footgun reducer, not a boundary.

One consequence deserves its own sentence: **restore is also code execution.** A snapshot is a `dill` pickle, unpickling runs `__reduce__`, and restore happens automatically on resume — before any model call. A writable snapshot row is therefore remote code execution in the agent's process. The snapshot store inherits the database's trust level exactly.
