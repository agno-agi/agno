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

Compaction also folds on demand, without waiting for the threshold:

```
POST /agents/{agent_id}/sessions/{session_id}/compact
```

The route always answers 200 with a `status`, because declining is a normal outcome:
a summary costs a few hundred tokens whatever it replaces, so folding a smaller span
would leave the context bigger. Branch on `compacted`, and show `message` verbatim.

| status | meaning |
|---|---|
| `compacted` | the fold happened; `record` carries the token counts |
| `not_worth_it` | the span is too small to pay for the summary replacing it |
| `nothing_to_fold` | the kept tail covers the whole conversation |
| `already_compacted` | a previous fold already covers everything foldable |
| `no_history` | the session has no stored history yet |
| `not_enabled` | compaction is not configured on this agent |
| `summary_failed` | the summarizer returned nothing |

## Files
- `compaction_os.py` - An AgentOS serving two agents:
  - **Research Agent** (`compaction-agent`) folds automatically at `compact_at_tokens`.
  - **Manual Compaction Agent** (`manual-compaction-agent`) has `compact_at_tokens=None`,
    so it folds only when the API asks.
- `rest_api_compaction.py` - Drive a fold over HTTP against the manual agent.

Two agents rather than one because a threshold and a manual call race each other: with
the automatic trigger on, the server usually folds first and a manual call then reports
`already_compacted` - work it did not do.

Sizing note: these agents are told to answer at length, so one turn costs roughly 10k
tokens. `compact_at_tokens` has to sit above a single turn or it trips on turn one and
re-evaluates every turn, mostly to decline.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.

## Run
- `.venvs/demo/bin/python cookbook/05_agent_os/21_compaction/compaction_os.py`
- Open the chat UI, pick the Research Agent, and ask several questions in one session.
- After the fourth turn the Behind the Scenes panel shows "Context compacted".

With that server running, drive a fold over the API instead:
- `.venvs/demo/bin/python cookbook/05_agent_os/21_compaction/rest_api_compaction.py`
- Run it twice - the second run reports `already_compacted`.
