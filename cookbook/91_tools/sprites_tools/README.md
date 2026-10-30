# Sprites tools

Give an Agno agent command execution in an existing [Fly.io Sprite](https://sprites.dev).
The same Sprite keeps its files and installed packages across commands and agent runs.

## Setup

Install the optional integration:

```sh
uv pip install 'agno[sprites]'
```

When testing this contribution from an Agno checkout, use:

```sh
uv pip install -e 'libs/agno[sprites]'
```

Provide `SPRITES_TOKEN` through your environment or secret manager. Choose an
existing Sprite you own; this example never creates or deletes one.

## Verify the workspace without an LLM

```sh
python cookbook/91_tools/sprites_tools/example.py --sprite YOUR_SPRITE
```

The check writes a uniquely named temporary file, reads it in a separate command,
and removes that file afterward. It needs Python inside the Sprite, but no model
API key. A successful check verifies filesystem continuity, not shared Python
interpreter state.

To run an agent, install your chosen Agno model provider's optional dependency,
configure that provider's credentials, and supply its `provider:model` ID:

```sh
python cookbook/91_tools/sprites_tools/example.py --sprite YOUR_SPRITE --model PROVIDER:MODEL
```

## Use in your application

```python
import os

from agno.agent import Agent
from agno.tools.sprites import SpritesTools
from sprites import SpritesClient

client = SpritesClient(token=os.environ["SPRITES_TOKEN"])
try:
    sprite = client.get_sprite("YOUR_SPRITE")
    tools = SpritesTools(sprite=sprite, timeout=60)
    agent = Agent(model="PROVIDER:MODEL", tools=[tools])
    agent.print_response("Use Python to calculate the first ten square numbers.")
finally:
    client.close()
```

`run_sprite_command(args)` accepts an executable and its arguments. They are passed
directly to the SDK; shell expansion requires an explicit `bash -lc` command.
Results are JSON with separate `stdout`, `stderr`, and `exit_code` fields. Nonzero
exit codes retain both streams. Each stream is limited to `max_output_chars`
(16,000 by default), keeping the end so final build errors survive truncation,
with per-stream truncation flags. This limit applies after SDK capture;
it does not bound transport buffering.

Configure a fixed `cwd` and `env` on `SpritesTools` if needed. The directory must
already exist. `cwd` is not a filesystem access restriction. Toolkit selection
and confirmation options, including `requires_confirmation_tools`, work normally.

Agno async runs use `arun_sprite_command`, registered under the same
`run_sprite_command` tool name. It runs the synchronous SDK on a worker thread,
including when async tool hooks are configured. The caller still supplies and
owns a synchronous `Sprite`. Cancelling the awaiting task does not stop the
worker thread or remote command.

## Lifecycle and failures

- The caller owns the Sprite and SDK client. `tools.close()` leaves both intact.
  Explicitly close the client when the application is finished with it.
- Reuse the same Sprite for persistent files. Each command starts a separate
  process; shell variables and Python interpreter memory do not carry over.
- A timeout bounds the SDK call and may leave the remote process running.
  Timeout and SDK failures return a null `exit_code`; the toolkit does not invent
  an exit status or automatically retry commands with potentially repeated side effects.
- SDK failures are logged locally with their diagnostic message. Treat those logs
  as potentially sensitive. Model-facing errors include the exception type and,
  for API errors, the HTTP status code; they omit diagnostic messages and bodies.
- This initial integration exposes command execution only. It does not provision
  Sprites or register deletion, checkpoint, or dedicated file-management tools.
