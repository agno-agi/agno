# VoicePipe test log

## 2026-10-02

### voice_computer_use.py

**Status:** NOT RUN

**Description:** Wraps the pyautogui computer use agent from
`cookbook/91_tools/computer_use/` in a VoicePipe with a 300-second response
timeout, `markdown=False`, and runs stored through `AgentOS(db=...)`. Confirmed
that Agno runs sync tools through `asyncio.to_thread`, so screen actions do not
block the voice session. Scoped Ruff passed.

**Result:** `--check` was not run because `pyautogui` is not installed in the
development environment. A live run needs provider keys and desktop control.

---

### voice_reasoning.py

**Status:** PASS for offline checks

**Description:** New example using the model's native reasoning
(`reasoning_effort`, default `low`, with `reasoning_summary="auto"`). Confirmed in
the agent's streaming code that reasoning deltas arrive with `content=None`, so the
pipe never speaks them, while the summary is stored on the run. Ran `--check` and
scoped Ruff.

**Result:** Route check passed. Live reasoning latency and answer quality are not
verified; that needs provider keys.

---

### GET /voice discovery endpoint

**Status:** PASS for automated checks

**Description:** Added `GET /voice`, which returns `id`, `agent_id`, `agent_name`,
and `path` for each live socket. Like `GET /agents`, it filters pipes by the
caller's agent read access. Its scope mapping is an explicit empty list because
`/voice` is not an agents path, so a mapped `agents:read` would reject tokens
scoped to one agent; a valid token is still required. Ran the voice router, voice
pipe, and scope unit suites.

**Result:** 123 tests passed. The new tests cover the listing and its `/docs`
entry, 401 without the security key or a JWT, and filtering for a token scoped
to one agent.

---

### SQLite run storage for the examples

**Status:** PASS for offline checks

**Description:** Added a `SqliteDb` to the agent in `voice_agent.py`, `voice_tools.py`,
and `voice_knowledge.py` so voice turns are saved as runs for AgentOS observability.
VoicePipe's in-call history is unchanged. Ran each `--check` and scoped Ruff.

**Result:** Checks passed. Saving runs during a live call has not been verified,
because that needs provider keys.

---

### Canonical /voice/{id}/pipe route and standalone client

**Status:** PASS for automated checks

**Description:** AgentOS now registers only the WebSocket route `/voice/{id}/pipe`
per live socket. The HTML page, `/voice/static/*` assets, their auth exemptions, the
reserved `static` ID, and the package-data entry were removed. The browser client
moved to `client/` with AgentOS URL and pipe ID fields, so one client serves all
three examples. Ran the voice unit suites, the moved Node client tests, each
cookbook's `--check`, and scoped Ruff.

**Result:** 82 Python tests and 8 Node tests passed. New tests confirm that the old
HTML, static, and `/ws` paths are gone and that `/pipe` connects. All three
`--check` runs resolve their `/voice/{id}/pipe` route. The client has not been
tried against a live server with a real microphone.

---

### voice_tools.py

**Status:** PASS for offline checks

**Description:** Ran the standalone example with `--check` in the development
environment after replacing the custom tools with Agno's `CalculatorTools` and
`WebSearchTools`. Checked toolkit registration, local multiply and divide-by-zero
calls, and voice routes. No web search request was made. Scoped Ruff lint and
formatting passed.

**Result:** Local tools and routes work without provider calls. Live model tool
selection, speech recognition, and spoken responses require a microphone test.

---

### voice_knowledge.py

**Status:** PASS for offline configuration checks

**Description:** Rewrote the example as an Agno docs agent that loads
`https://docs.agno.com/llms.txt` into a local hybrid-search LanceDB table,
following `cookbook/03_teams/05_knowledge/01_team_with_knowledge.py`. Ran `--check`
in the development environment to confirm the knowledge configuration and voice
route.

**Result:** Configuration and route checks passed. This command does not read API
keys, download the docs, create embeddings, or contact a model. Live retrieval and
spoken answers are not claimed by this check.

---

### Playback overflow regression and UI redesign

**Status:** PASS for automated pipeline, browser-code, and headless browser checks

**Description:** Investigated the reported immediate playback-buffer error. The
old browser guard subtracted a device presentation timestamp from a scheduling
timestamp, so a stale output clock could falsely exceed the 30-second limit on
the first short packet. Separately, the server sent generated speech without
waiting for playback, allowing fast long replies to exceed the legitimate limit.
Neither mechanism requires a provider credential to reproduce.

**Result:** Browser limits now count unplayed samples, with a latency-adjusted
clock fallback for stale device timestamps. Server delivery waits for playback
acknowledgments and stays at most two seconds ahead. The current combined Python
suite passes 85 tests. Eight Node regression tests pass, including a short first
packet after 90 seconds, partial-playback interruption accounting, a paced
40-second answer, malformed offsets, actual over-capacity rejection, and loading
state accessibility. Scoped Ruff checks pass. No keys were accessed and no live
provider requests were made for this change.

Headless Chrome also passed six cases using a local mock server and synthetic
microphone: ordinary playback and controls, a stale output clock after a simulated
40-second wait, interruption with stale audio rejection, oversized burst rejection,
mobile layout, and a real-time 36-second paced reply. The long reply acknowledged
all 864,000 samples, kept outstanding audio at or below 48,000 samples (two seconds),
and captured 1,155 correctly sized microphone frames. No browser errors occurred.
Connecting/thinking spinners were visible. Desktop and mobile screenshots were
visually inspected with no horizontal overflow. This is not a live Cartesia test.

**Commands:**

```text
.venv/Scripts/python.exe -m pytest libs/agno/tests/unit/voice libs/agno/tests/unit/os/test_voice_router.py -q -p no:cacheprovider
node --test libs/agno/tests/unit/voice/test_voice_client.mjs
```

**Design reference:** Fetched only design sources from Agent UI, without cloning:
[theme tokens](https://raw.githubusercontent.com/agno-agi/agent-ui/main/tailwind.config.ts),
[global CSS](https://raw.githubusercontent.com/agno-agi/agent-ui/main/src/app/globals.css),
[button styles](https://raw.githubusercontent.com/agno-agi/agent-ui/main/src/components/ui/button.tsx),
and [sidebar layout](https://raw.githubusercontent.com/agno-agi/agent-ui/main/src/components/chat/Sidebar/Sidebar.tsx).
The page uses a charcoal/orange palette and includes connecting/thinking spinners.

---

### Voice pipeline, providers, and AgentOS routing

**Status:** PASS

**Description:** Ran `pytest libs/agno/tests/unit/voice
libs/agno/tests/unit/os/test_voice_router.py -q` in the development environment.

**Result:** 77 tests passed, including streaming, cancellation, playback history,
provider protocols, timeouts, per-call isolation, authentication, and browser origin
checks. Pytest reported a cache permission warning and an existing dependency
deprecation warning. These tests use mocked providers.

---

### Package and static checks

**Status:** PASS for scoped checks; repository-wide validation incomplete

**Description:** Built the SDK wheel and inspected its contents. Ran scoped Ruff
lint/format checks and mypy on the voice modules and router.

**Result:** The wheel includes all voice modules and all three browser assets.
Scoped checks passed. A broader mypy run encountered unrelated dependency/type
errors; a subsequent broad run was stopped without a result. Full repository
validation is not claimed.

---

### Browser JavaScript syntax

**Status:** PASS

**Description:** Checked the browser client as an ECMAScript module and the capture
worklet with Node's syntax checker.

**Result:** Both assets parse successfully.

---

### Browser microphone and playback smoke

**Status:** PASS

**Description:** Headless Chrome used a synthetic microphone and a local mock
WebSocket server. Verified 61 captured frames were exactly 768 PCM16 samples,
streamed text appeared, cumulative playback acknowledgments reached the expected
12,000 samples, mute and end controls worked, and no JavaScript errors occurred.

**Result:** Desktop (1280 px) and mobile (390 px) layouts rendered without horizontal
overflow. Screenshots were visually inspected. This uses real browser audio APIs
but synthetic speech and mocked provider events.

---

### voice_agent.py configuration check

**Status:** PASS

**Description:** The cookbook's `--check` exercises the registered browser routes
without opening provider connections.

**Result:** `--check` returned success with both default Cartesia and
`VOICE_TTS_PROVIDER=openai` configurations. Ruff lint and formatting checks passed
for the cookbook. The development environment was used because a demo environment
was not available.

---

### Capture resampling and interruption playback accounting

**Status:** PASS

**Description:** Node VM checks fed a continuous sine wave through the capture
worklet at 24, 44.1, and 48 kHz, verifying fixed 768-sample PCM frames and continuous
resampling. A controlled output clock exercised queued, partly played, and canceled
audio in the browser client.

**Result:** Unheard scheduled audio was not acknowledged; interruption acknowledged
only the approximately 4,800 of 12,000 samples already played, stopped the source,
and rejected later audio belonging to the canceled reply.

---

### OpenAI-only live provider smoke

**Status:** PASS for functional behavior; latency target not met

**Description:** A local smoke driver sent a synthetic 2.75-second recording of
"What are you, and what can you do?" through the live OpenAI-only pipeline.
The final transcript was "What are you? And what can you do?" and the pipeline
produced 710,400 bytes of PCM speech output.

**Result:** Recognition stayed in English. Measured from VAD speech end:

| Stage | Elapsed |
| --- | ---: |
| Final transcript | 788 ms |
| First agent token | 3,104 ms |
| First audio sent | 4,660 ms |

Agent startup to first token took 2,316 ms; first token to first audio took 1,556 ms.
These measurements exclude the 320 ms silence window and browser playback. This
single synthetic-audio run verifies functionality, not conversational quality or
latency parity with Pipecat or LiveKit. The intended sub-second response target
was not met.

---

### Cartesia live provider conversation

**Status:** NOT RUN

**Description:** The default persistent Cartesia speech path requires a
`CARTESIA_API_KEY`, which was unavailable during validation.

**Result:** No live Cartesia latency or audio-quality result is claimed. A real
microphone conversation and repeated latency measurements remain necessary.

---

### Talker model comparison

**Status:** PASS for OpenAI and Google requests; Groq authentication failed

**Description:** Made two sequential streaming Agno requests per working provider
with the same short voice prompt. These are text-only timings, not microphone
end-to-end measurements.

| Model | First request: first token | Reused client: first token |
| --- | ---: | ---: |
| OpenAI `gpt-5.6-luna`, reasoning disabled | 1,776 ms | 763 ms |
| Google `gemini-3.5-flash-lite`, minimal thinking | 2,210 ms | 706 ms |

**Result:** The small sample does not establish a consistently faster provider.
Kept the existing default. Groq returned HTTP 401 and was not benchmarked further.
