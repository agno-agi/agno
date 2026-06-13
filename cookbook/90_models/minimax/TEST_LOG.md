# TEST_LOG

Tests run against the MiniMax OpenAI-compatible endpoint
(`https://api.minimax.io/v1`) with `MINIMAX_API_KEY` set. Default model id
is `MiniMax-M3`.

### basic.py

**Status:** PASS

**Description:** Sync and sync+streaming invocations of `MiniMax-M3`. Tests
that thinking is rendered in the Thinking panel and the final answer alone
in the Response panel.

**Result:** Both modes return a 2-sentence horror story. Thinking panel
contains the reasoning trace; Response panel contains only the answer (no
raw `<think>` tags). MiniMax-M3 streams reasoning over **two channels**
simultaneously — a structured `reasoning_content` field plus inline
`<think>...</think>` tags in the content stream. The `MiniMax` model class
overrides `invoke_stream`/`ainvoke_stream` to strip the inline tags
(stateful filter, handles tags split across chunks); the structured field
drives the Thinking panel.

---

### structured_output.py

**Status:** PASS

**Description:** Pydantic-shaped output (`MovieScript`, six fields including
a list) via `use_json_mode=True`.

**Result:** `MiniMax-M3` returned a valid `MovieScript` instance with all
six fields populated (setting / ending / genre / name / characters /
storyline). MiniMax does not implement OpenAI-style native
`response_format`/`json_schema` (`supports_native_structured_outputs =
False`), so structured output is driven through JSON mode rather than the
strict-schema path.

---
