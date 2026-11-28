# Google ADK

Examples for running Google ADK (Agent Development Kit) agents through Agno.

ADK is Google's framework for Gemini-native agents and agent trees: an
`LlmAgent` with Python-function tools, and workflow agents (`SequentialAgent`,
`ParallelAgent`, `LoopAgent`) that compose them. `GoogleADKAgent` wraps the root
of such a tree so it runs standalone with `print_response()` or is served by
AgentOS with the same API, streaming, session storage and UI as native agents.

How the pieces map:

| ADK | Agno |
|---|---|
| `Runner` | Built by the adapter, or pass your own with `runner=` |
| Session (`app_name`, `user_id`, `session_id`) | The Agno session id and user id; `default_user_id` fills in when a run has no user |
| Session service | `session_service=`; in memory by default, so native context lasts for the process. Agno's db stores the runs and replays them into a fresh ADK session |
| Streamed partial text | `RunContentEvent` |
| Function call / function response | `ToolCallStartedEvent` / `ToolCallCompletedEvent` |
| `usage_metadata` | Run metrics (tokens per model) |
| `RunConfig` | `run_config=`; streaming runs use SSE mode |
| Images, audio, video, files | Native parts of the user message |

## Setup

```bash
pip install google-adk
export GOOGLE_API_KEY=...
```

## Files

- `google_adk_basic.py` - minimal standalone run
- `google_adk_tools.py` - function tools, shown as tool events while streaming
- `google_adk_multi_agent.py` - a `SequentialAgent` tree served as one agent
- `google_adk_session.py` - multi-turn session with runs stored in SQLite
- `google_adk_image.py` - an image sent to Gemini as a native part
- `google_adk_agentos.py` - the same agent behind AgentOS endpoints

Structured output is configured on the ADK agent (`LlmAgent(output_schema=...)`);
the adapter does not take Agno's `output_schema` option. Long-running tools and
tool confirmations pause the ADK invocation and are not resumed by the adapter.

Test results are tracked in `TEST_LOG.md`.
