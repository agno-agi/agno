# CodeMode

**CodeMode** gives the agent one programmable environment instead of a wide tool schema. The model writes Python; the code runs in an IPython kernel that lives as long as the session. Variables, imports, helper functions, and parsed tool results survive across turns. Every other toolkit you attach becomes a callable inside that kernel rather than a separate entry in the model's tool list, so a tool call is an `await` expression the model can bind to a variable, loop, and compose.

CodeMode caps what a cell can print, so the context holds conclusions and the kernel holds the data. Its sibling for ordinary tools is result offloading, `Agent(offload_tool_results=True)`, in [`../02_agents/22_result_offloading/`](../02_agents/22_result_offloading/).

Start with [`01_basics/basic.py`](01_basics/basic.py).

## Install

CodeMode needs an optional extra:

```bash
pip install 'agno[code]'
```

## Layout

````
cookbook/code/
├── README.md
├── 01_basics/                 # one tool, a live kernel
├── 02_tools_in_code/          # toolkits as awaitable handles
└── 03_persistence/            # state that survives the process
````

## Folders

- [`01_basics/`](01_basics/): the smallest working agent, and `%%bash` shell cells.
- [`02_tools_in_code/`](02_tools_in_code/): binding a toolkit into the kernel, and composing with the agent filesystem.
- [`03_persistence/`](03_persistence/): dill snapshots into AgentFS, and the developer-facing surface (`run` / `variables` / `value` / `shutdown`).

## Security

`execute` runs arbitrary Python and arbitrary shell with the permissions of the process running the agent. It is not a sandbox and does not pretend to be one: use a trusted operator or an isolated container. `allow_shell=False` strips the `%%bash` magic, but that is a footgun reducer, not a boundary.

One consequence deserves its own sentence: **restore is also code execution.** A snapshot is a `dill` pickle, unpickling runs `__reduce__`, and restore happens automatically on resume — before any model call. A writable snapshot row is therefore remote code execution in the agent's process. The snapshot store inherits the database's trust level exactly. For the same reason, never point another writer at the FileSystem namespace CodeMode snapshots into - a `FileSystemTools` that can write `kernel/<session>/vars/*.b64` there lets whatever drives it plant a payload the next resume unpickles.

A session's environment belongs to the user of the run that created it, in memory and in the snapshot. A run that names the same `session_id` with a different `user_id` is refused and gets neither the warm kernel nor the stored variables. Runs without a `user_id` carry no identity to compare and keep sharing a session by id; such a run takes the recorded owner rather than clearing it, so a later run by a different user is still refused. Identity is compared as text, so `42` and `"42"` are the same user.
