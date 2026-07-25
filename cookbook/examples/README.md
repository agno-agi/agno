# Agno Examples

The numbered cookbooks teach primitives. This folder builds products: small, complete agents,
each one doing something a chat app cannot do for you.

## The examples

### [second_brain](./second_brain) — memory you own, behind your own MCP server

Durable notes in the agent's own filesystem, keyed per user, plus what it learns about how you
work. Because it is an MCP server, Claude, ChatGPT and your own scripts all read and write the
same brain. A chat app remembers you inside its walls; this store is yours and outlives any
one vendor.

### [metrics_desk](./metrics_desk) — your production database, answerable from any MCP client

The client sends a question, this process runs the SQL over a read-only connection, and only
the answer crosses the wire. Your credentials and your rows never leave. Ask it to drop the
table and the SQLite driver refuses, so the guarantee does not depend on the model behaving.

### [team_brain](./team_brain) — one decision log the whole team writes into

Everyone points their AI apps at the same endpoint. The author of a decision is taken from the
token the client authenticated with, so a caller cannot log a decision as someone else, and
one teammate reads another's decisions back with the right name on them.

### [house_rules](./house_rules) — what your rules are actually worth, measured

The same agent routes the same four tickets twice: once against an empty knowledge base, once
after your three routing rules have been inserted. Nothing else changes, so the two pass rates
are comparable. 0.25 before, 1.00 after, plus a per-task diff of exactly what moved.

## Running an example

Set up and activate the virtual environment:

```bash
./scripts/demo_setup.sh
source .venvs/demo/bin/activate
```

Export your API key. `OPENAI_API_KEY` is the only one any of these need:

```bash
export OPENAI_API_KEY=...
```

Then run an example from its own folder:

```bash
cd cookbook/examples/second_brain

# Drive the agent from the command line
python test.py

# Or serve it: AgentOS on http://localhost:7777, MCP on http://localhost:7777/mcp
python second_brain.py
```

Every folder is the same two files. `<example>.py` builds the agent and serves it, `test.py`
drives that same agent from the command line. Each folder writes its store to `tmp/` next to
the script, which is why both commands are run from inside the folder. `house_rules` is a
measurement rather than a service, so it is one script with nothing to serve.

Each folder's `TEST_LOG.md` records what a real run of both entry points produced.
