# Sprites tools test log

## 2026-10-06

### `example.py --help`

**Status:** PASS

**Description:** Ran CLI help with Python 3.14.6 and `sprites-py==0.7.1`.

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
This mocked check does not verify model selection or live tool calling; see the
separate live-run entries below.

---

### `example.py --sprite YOUR_SPRITE` (live Sprite, no model)

**Status:** PASS

**Description:** Manual execution against an existing Sprite with credentials
supplied through the environment. The result below was reported by the contributor.

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
