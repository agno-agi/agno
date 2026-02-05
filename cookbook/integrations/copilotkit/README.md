# CopilotKit + Agno (with session persistence)

Working example: Agno backend with session DB and AG-UI, used with a **CopilotKit 1.5** frontend. Loading an old session and sending a new message works without `tool_use`/`tool_result` errors because Agno restores missing tool results when replaying history.

## Prerequisites

- **Node.js 20+**
- **Python 3.9+**
- **OpenAI API key**
- **agno** with AG-UI: `pip install "agno[agui]"`

## 1. Run the Agno backend

From this directory (`cookbook/integrations/copilotkit/`):

```bash
# Optional: set OpenAI key
export OPENAI_API_KEY=your_key

# Run the backend (AG-UI + session router on port 8000)
python agent.py
```

Or with uvicorn:

```bash
uvicorn agent:app --host 0.0.0.0 --port 8000 --reload
```

Backend serves:

- **AG-UI** at `http://localhost:8000/agui` (for CopilotKit)
- **Session API** at `http://localhost:8000/sessions` (list/get sessions, get runs)

## 2. Frontend with CopilotKit 1.5

Use a CopilotKit app that talks to this backend and pin CopilotKit to **1.5.x** (e.g. `@copilotkit/runtime@1.5.19`).

**Option A – New app with CopilotKit CLI (then pin to 1.5):**

```bash
npx copilotkit@1.5 create-f agno
cd <project-name>
npm install
# Pin CopilotKit to 1.5.x in package.json if needed, e.g.:
#   "@copilotkit/runtime": "1.5.19"
#   "@copilotkit/react-core": "1.5.19"
#   "@copilotkit/react-ui": "1.5.19"
```

**Option B – Use [CopilotKit/with-agno](https://github.com/CopilotKit/with-agno) and pin to 1.5:**

```bash
git clone https://github.com/CopilotKit/with-agno.git
cd with-agno
# In package.json set "@copilotkit/runtime", "@copilotkit/react-core", "@copilotkit/react-ui" to "1.5.19"
npm install
```

Configure the frontend so the Agno backend URL is `http://localhost:8000` (or your backend URL). Start the UI (e.g. `npm run dev`).

## 3. Verify (session load + new message)

1. In the CopilotKit UI, start a new thread and send a message that uses a tool (e.g. “Show ‘Hello’ in the UI”).
2. Note the session/thread id (or use “list sessions” from the session API).
3. Reload the app and **load that same session** (e.g. via session list or thread picker).
4. Send a new message, e.g. “hey”.

You should **not** see:

`messages.1: tool_use ids were found without tool_result blocks immediately after...`

Agno’s session loader fills in missing tool results when building history, so the model always gets valid `tool_use` + `tool_result` pairs.

## Backend behavior

- **`agent.py`**: Agent with one frontend tool (`show_in_ui`), SQLite session DB, and AG-UI. Session router and AG-UI use the same DB; when a session is loaded, history is sanitized so every tool call has a matching tool result before being sent to the model.

## Docs

- [CopilotKit + Agno](https://docs.copilotkit.ai/agno/quickstart)
- [Agno session/router behavior](https://docs.agno.com)
