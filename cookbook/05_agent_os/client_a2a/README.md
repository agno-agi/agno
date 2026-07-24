# DEPRECATED: agno.client.a2a examples

The examples that lived here used `agno.client.a2a.A2AClient`, Agno's
hand-rolled A2A client. That client predates A2A 1.0 and is **deprecated** —
it now emits a `DeprecationWarning` on use.

## Use these instead

- **Call an A2A agent from an Agno agent** — the `A2AClient` toolkit from
  `agno.tools.a2a` (wraps the official `a2a-sdk` client, one instance per
  remote agent):
  - `cookbook/91_tools/a2a/` — toolkit quick start
  - `cookbook/05_agent_os/interfaces/a2a/basic_agent/` — minimal server + client pair
  - `cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/` — orchestrator coordinating multiple remote agents

- **Expose an Agno agent over A2A** — `AgentOS(a2a_interface=True)`:
  - `cookbook/05_agent_os/interfaces/a2a/`

- **Use a remote Agno entity as a first-class object** — `RemoteAgent`,
  `RemoteTeam`, `RemoteWorkflow` (`agno.agent.remote` etc.).

- **Raw protocol access from any language/framework** — the official
  `a2a-sdk` client directly; see
  `cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/streaming_client_demo.py`
  and `agent_card_demo.py`.
