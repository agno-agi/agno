# Agno Examples

The numbered cookbooks teach primitives. This folder showcases small, complete agents.

## The examples

- [second_brain](./second_brain) - memory you own, behind your own MCP server
- [metrics_desk](./metrics_desk) - your production database, answerable from any MCP client
- [team_brain](./team_brain) - one decision log the whole team writes into
- [house_rules](./house_rules) - what your rules are actually worth, measured

## Running an example

Set up and activate the virtual environment:

```bash
./scripts/demo_setup.sh
source .venvs/demo/bin/activate
```

Export your API key.

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

`house_rules` is a measurement rather than a service, so it is one script with nothing to
serve and no `test.py`:

```bash
cd cookbook/examples/house_rules
python house_rules.py
```

The other three folders are `<example>.py`, which builds the agent and serves it, and `test.py`, which runs that same agent from the command line.
