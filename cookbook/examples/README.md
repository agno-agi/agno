# Agno Examples

This folder showcases unique examples not covered by the numbered cookbooks. The numbered cookbooks focus on primitives, whereas this folder focuses on interesting products you can build with Agno.

## Running an example

Setup and activate the virtual environment:

```
./scripts/demo_setup.sh
source .venvs/demo/bin/activate
```

```bash
cd cookbook/examples/second_brain
../../../.venvs/demo/bin/python second_brain.py
```

Run the folder to serve it as an MCP endpoint (`house_rules` is pure measurement and has nothing to serve). Each serving folder's `__main__.py` pins the working directory to the example folder first, so this form works from anywhere:

```bash
.venvs/demo/bin/python cookbook/examples/second_brain
```

All four examples need only `OPENAI_API_KEY`; nothing here wants docker or a second key. Each folder's README states what you will see, how to point an MCP client at it where relevant, and the Postgres swap for production. The demos all exit on their own, so `cookbook_runner.py cookbook/examples -r` sweeps the whole folder (`__main__.py` files are skipped by the runner and the pattern checker).
