# Warp Tools AgentOS

This cookbook serves one AgentOS agent with every `WarpTools` function.

## Files

| File | What it does |
|---|---|
| `warp_tools_agent.py` | Serves the Warp agent on port 7777 with every tool enabled. |
| `TEST_LOG.md` | Records the validation status for this lesson. |

## Features covered

| Tool | Expected behavior | Confirmation |
|---|---|---|
| `open_window` | Open a Warp window in the repository. | No |
| `open_tab` | Open a Warp tab in the repository. | No |
| `run_commands` | Generate a temporary Tab Config, open it as a new Warp tab, and run the requested commands. | No |
| `open_launch_config` | Open one of the user's saved Launch Configurations. | Yes |
| `open_tab_config` | Open one of the user's saved Tab Configs. | Yes |
| `run_agent` | Run an Oz prompt and return its output to Agno. | Yes |

`run_commands` creates and opens its temporary Tab Config directly so it can
be tested from AgentOS without a continuation step. The generated file is
removed after Warp has had time to open it. The saved config launchers and
`run_agent` retain confirmation because they may execute saved or
agent-generated commands.

## Prerequisites

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
oz login
```

Install Warp desktop and make sure `oz` is on `PATH`. This cookbook controls a
local GUI session, so it is not suitable for a headless server.

## Start AgentOS

```bash
.venvs/demo/bin/python cookbook/05_agent_os/26_warp_tools/warp_tools_agent.py
```

Inspect [http://localhost:7777/config](http://localhost:7777/config) to confirm
that `warp-tools-agent` is registered. Connect the OS at
[https://os.agno.com](https://os.agno.com), select the Warp Tools Agent, and
ask it to call the desired function. For example:

```text
Open a new Warp window in /path/to/project.
Open a new Warp tab in /path/to/project.
Run "pwd" in a new Warp tab at /path/to/project.
Open my saved Warp Launch Configuration named dev.
Open my saved Warp Tab Config named dev.
Run a Warp agent that summarizes /path/to/project without editing files.
```

## Verification boundary

Window, tab, configuration, and command actions are fire-and-forget. AgentOS
cannot verify command output, so inspect the new Warp tab opened by
`run_commands`. `run_agent` is the only feature that returns captured output
through Oz.
