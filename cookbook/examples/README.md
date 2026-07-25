# Examples

Agents worth having, one folder each. The numbered cookbooks answer "how does feature X work"; this folder answers "what can I build". Every example here is one file you can read in a screen or two, run on the first try, and it proves at runtime one thing a chat app or coding agent cannot do.

| Example | What it is | Why it is here | Needs |
|---|---|---|---|
| [second_brain](second_brain) | A private agent that remembers what you are building, behind your own MCP server | a chat app cannot do this because the endpoint is yours and the store outlives any one vendor | `OPENAI_API_KEY` |
| [metrics_desk](metrics_desk) | Your database, answerable from any MCP client, on a connection the model cannot escalate | a chat app cannot do this because the connection opens read-only before the model exists, and only the answer crosses the wire | `OPENAI_API_KEY` |
| [team_brain](team_brain) | A shared team decision log where every entry is attributed to the token that wrote it | a chat app cannot do this because the caller cannot type who they are; the author comes off the token | `OPENAI_API_KEY` |
| [house_rules](house_rules) | A before/after measurement of what your team's routing rules are worth | a chat app cannot do this because it cannot show you the number, run your tasks k times, and prove the two runs were comparable | `OPENAI_API_KEY` |

This folder deliberately does not contain deep researchers, chatbots, RAG demos or code reviewers: chat apps do those too, so they fail the second test. They live in the numbered cookbooks, which also own feature and provider breadth: [02_agents](../02_agents) for the agent feature surface, [07_knowledge](../07_knowledge) for knowledge and vector databases, [90_models](../90_models) for model providers.

## Running an example

`cd` into the example's folder and run it with the demo venv:

```bash
cd cookbook/examples/second_brain
../../../.venvs/demo/bin/python second_brain.py
```

Databases land in that folder's `tmp/`, so run from the example folder, not the repo root. All four examples need only `OPENAI_API_KEY`; nothing here wants docker or a second key. Each folder's README states what you will see, how to point an MCP client at it where relevant, and the Postgres swap for production.

Note for maintainers: `metrics_desk.py` and `team_brain.py` are servers and run until stopped, so a folder-wide `cookbook_runner.py` sweep will block on them until its per-script timeout. Sweep the two scripted examples instead (`--pattern second_brain.py`, `--pattern house_rules.py`) and verify the servers with an MCP client as their TEST_LOGs do.
