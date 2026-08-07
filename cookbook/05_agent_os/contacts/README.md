# Contacts Cookbook

Examples for contacts: letting an agent message other user-built agents and teams.

A `Contact` (`agno.contacts.Contact`) wraps an existing entity — a local `Agent`
or `Team`, or a `RemoteAgent`/`RemoteTeam` on another AgentOS — together with
instructions on when to contact it:

```python
from agno.contacts import Contact

news_reporter = Contact(agent=news_agent, instructions="Contact to get the latest news")
agent = Agent(model=..., contacts=[news_reporter])
```

The agent gets a `message_contact` tool whose description enumerates the contact
list. A contacted entity runs like a child run inside the agent's session, just
like team member delegation: its events stream nested into the chat under the
contact's own name (via `parent_run_id`), and its answer becomes the tool result.
Contacts keep their own history and persistence; the parent's context stays clean.

Remote contacts ride on the RemoteAccess interface (see `../remote/`): only
entities the remote AgentOS explicitly exposes are contactable, and they can only
be messaged in async runs (`arun`), which is what AgentOS uses.

## Files

- `server.py` — News agency AgentOS (port 7778). Exposes `news-agent`, `publish-team` and `coding-agent` (with GitHub access for issues and PRs) via RemoteAccess. The coding agent's own contact is the remote customer support agent.
- `01_joke_writer.py` — The flagship (port 7777): a freelance joke writer with a local safety-check contact, a remote news agent contact and a remote publishing team contact.
- `02_contacts_local.py` — All-local variant (port 7777): an assistant with a docs agent contact and a research team contact. No server needed.
- `03_support_agent.py` — Customer support AgentOS (port 7779): escalates technical problems to the remote coding agent, and exposes itself via RemoteAccess so the coding agent can contact it back — mutual cross-OS contacts with no circular object wiring.
- `04_personal_agent.py` — Personal agent (port 7777): a generalist with its own tools plus remote news and coding contacts.

## Running

1. For the joke writer, start the news agency server first:
   ```
   .venvs/demo/bin/python cookbook/05_agent_os/contacts/server.py
   ```
2. In a second terminal, start an example app:
   ```
   .venvs/demo/bin/python cookbook/05_agent_os/contacts/01_joke_writer.py
   ```
3. Chat with the agent at http://localhost:7777 (connect via os.agno.com) and watch
   contacted entities stream nested under the parent run, labeled with their name:
   - "Write a joke about the latest tech news and get it published" runs the full
     news -> joke -> safety check -> publish chain.

## Notes

- Exactly one of `agent=` or `team=` per Contact; `instructions=` is what the model
  sees in the contact list; `name=` overrides the key used to address the contact.
- Agent contacts share the parent's session; team contacts run in a session derived
  from it. Nothing from a contact's run enters the parent's message history.
- Remote contacts require async runs; the sync path returns a clear error message.
- If the remote server is down, messaging its contacts fails with a clean error
  string and the parent agent carries on.

## Prerequisites

- Set your `OPENAI_API_KEY` environment variable.
- For the coding agent's GitHub tools, set `GITHUB_ACCESS_TOKEN`.
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
