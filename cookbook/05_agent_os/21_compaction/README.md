# 21_compaction

Conversation compaction served on AgentOS, with the fold visible in the chat UI.

Compaction keeps a long session inside the model's context window: once the
conversation crosses a threshold, older turns are folded into a summary and the
recent ones are kept verbatim. The stored transcript is never rewritten, so the
session still holds every message - only what is sent to the model gets shorter.

Two events stream to the UI while a fold runs:

| Event | Carries |
|---|---|
| `CompactionStarted` | run and session ids |
| `CompactionCompleted` | `messages_compacted`, `tokens_before`, `tokens_after`, `archived` |

Agno OS renders these in the Behind the Scenes panel of a chat, so a long
conversation shows what happened to its context instead of silently losing turns.

## Files
- `compaction_os.py` - An AgentOS serving one agent with compaction enabled.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.

## Run
- `.venvs/demo/bin/python cookbook/05_agent_os/21_compaction/compaction_os.py`
- Open the chat UI, pick the Research Agent, and ask several questions in one session.
- After the fourth turn the Behind the Scenes panel shows "Context compacted".
