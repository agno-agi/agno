# Eden AI — Test Log

### basic.py

**Status:** PASS

**Description:** Runs `Agent(model=EdenAI(id="openai/gpt-5.5"))` against Eden AI's
OpenAI-compatible Chat Completions endpoint (`https://api.edenai.run/v3`) across all four
variants: sync, sync + streaming, async, and async + streaming.

**Result:** All four variants returned successfully. The endpoint was independently verified
to return HTTP 200 for `openai/gpt-5.5`, `openai/gpt-5`, `openai/gpt-4.1-mini` and
`mistral/mistral-large-latest` (Eden AI addresses models as `<provider>/<model>`).

---
