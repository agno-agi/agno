# Agno Examples

This folder showcases unique examples not covered by the numbered cookbooks. The numbered cookbooks focus on primitives, whereas this folder focuses on interesting products you can build with Agno.

## Running an example

Setup and activate the virtual environment:

```bash
./scripts/demo_setup.sh
source .venvs/demo/bin/activate
```

Export your API key(s):

```bash
export OPENAI_API_KEY=...
```

Run an example from its own folder:

```bash
cd cookbook/examples/second_brain

# Drive the agent from the command line
python test.py

# Or serve it: AgentOS on http://localhost:7777, MCP on http://localhost:7777/mcp
python second_brain.py
```

Every folder is the same two files. `<example>.py` builds the agent and serves it, `test.py` drives that same agent from the command line. Each folder writes its store to `tmp/` next to the script, which is why both commands are run from the folder. `house_rules` is a measurement rather than a service, so it is one script with nothing to serve.
