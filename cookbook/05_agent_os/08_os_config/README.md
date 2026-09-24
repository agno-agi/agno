# AgentOS configuration

`AgentOSConfig` controls how a running OS presents its components and data
domains to the control plane. These examples define the same concepts in
Python and YAML, then read `GET /config` to prove what AgentOS rendered.

## Files

| File | What it teaches |
|---|---|
| `config_basics.py` | Define available models, per-agent manifest metadata, quick prompts, and named session/memory domains in Python. |
| `yaml_config.py` | Load those fields from `config.yaml` and verify the rendered configuration. |
| `config.yaml` | Declarative AgentOSConfig values whose IDs match the Python runtime objects. |

## Prerequisites

Configuration inspection needs no external credentials. Set `OPENAI_API_KEY`
only when you also want to run the configured agent.

## Run the Python configuration

Terminal 1:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/08_os_config/config_basics.py
```

Terminal 2:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/08_os_config/config_basics.py --demo
```

The manifest key is the explicit agent ID `operations-agent`. Labels appear on
the component card and `quick_prompts` appear in chat. `available_models`
controls the model choices presented by the UI; it does not replace the model
configured on the Agent itself.

The session and memory entries name how the same real SQLite database appears
in the control plane. An explicit domain entry takes precedence for its
`db_id`; AgentOS auto-discovers and appends only databases that do not already
have an entry.

## Run the YAML configuration

Terminal 1:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/08_os_config/yaml_config.py
```

Terminal 2:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/08_os_config/yaml_config.py --demo
```

YAML is useful when operators should change UI metadata without editing Python.
Python is preferable when configuration is assembled conditionally or shared
with typed application constants. In both cases, Python still creates the
runtime agents and databases: YAML configures their presentation, so its
manifest keys and `db_id` values must match those objects. Passing a YAML path
as `config=` selects the YAML values; passing an `AgentOSConfig` object selects
the in-code values.

This example intentionally registers no messaging interfaces. Interfaces are
runtime objects passed to `AgentOS(interfaces=[...])`, not phantom YAML
declarations.

## Input schemas and the chat form

An Agent, Team, or Workflow can define an `input_schema`. The chat UI discovers
components through `/config`, fetches the selected component's detail response,
and uses its JSON schema to render a structured form. See
[`09_serving_workflows/with_input_schema.py`](../09_serving_workflows/with_input_schema.py)
for a workflow and a live `GET /workflows/{id}` check.
