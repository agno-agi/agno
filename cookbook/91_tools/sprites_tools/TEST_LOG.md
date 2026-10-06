# Sprites tools test log

## 2026-10-06

### `example.py --help`

**Status:** PASS

**Description:** Ran with `.venvs/demo/bin/python` on Python 3.14.6 and
`sprites-py==0.7.1`.

**Result:** Imports succeeded and CLI help described both execution modes.

---

### `example.py --sprite mock-sprite` (mocked SDK)

**Status:** PASS

**Description:** Executed the script's main entry point with a mocked
`SpritesClient` and SDK `CompletedProcess` results. No network requests were made.

**Result:** The workspace check wrote, read, and removed the same uniquely named
file path through `run_sprite_command`, printed its success message, and closed
the client. No agent was created and no Sprite was deleted. This verifies the
example's control flow; see the separate live run below for filesystem persistence.

---

### `example.py --sprite mock-sprite --model test:model` (mocked SDK and Agent)

**Status:** PASS

**Description:** Executed the script's main entry point with mocked SDK and Agent
objects. No network or model requests were made.

**Result:** The model ID, Sprite toolkit, and `run_sprite_command` instructions
were passed to the Agent; `print_response` was called and the client was closed.
Model selection, tool calling by an actual model, and remote execution are unverified.

---

### `example.py --sprite YOUR_SPRITE` (live Sprite, no model)

**Status:** PASS

**Description:** The contributor ran the example against an existing Sprite with
`SPRITES_TOKEN` configured, using the prepared Python environment and the Agno
source at commit `3a23e48`. This entry records the contributor's terminal output;
the run was not executed by Codex.

**Result:** The example printed:

```text
Workspace check passed: the second command read the first command's file.
```

This confirms file continuity between separate commands in a live Sprite. The
example then removes its uniquely named temporary file; no cleanup warning was
present in the reported output. No model was used.

---

### `example.py --sprite YOUR_SPRITE --model PROVIDER:MODEL` (live Sprite and model)

**Status:** NOT RUN

**Description:** The model-backed run still requires a configured provider and a
live execution of this command.

**Result:** Tool calling by an actual model remains unverified. Run the model
example from README.md before marking this check passed.

---

### Adapter regression suite

**Status:** PASS

**Description:** Ran `libs/agno/tests/unit/tools/test_sprites.py` on Python 3.10.20
and 3.12.13 with the published `sprites-py==0.7.1`.

**Result:** 29 tests passed on each version, including 30 real SDK timeout races
per version with the WebSocket transport patched to hang, all three timeout
exception classes, both ShellTools ordering cases, and async tool hooks.
