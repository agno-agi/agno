# Streaming voice with AgentOS

Wrap an existing Agno `Agent` in a `VoicePipe` and register it with
`AgentOS(live_sockets=[voice])`. The agent keeps its configured model, tools,
knowledge, and instructions. VoicePipe handles microphone audio, turn detection,
streaming transcription, streaming agent output, speech synthesis, and interruption.
It does not depend on Pipecat or LiveKit.

AgentOS stays a backend: each live socket adds exactly one route, the WebSocket
`/voice/{id}/pipe`. It serves no voice page. `client/` is a standalone test client
that works with every example here, and [INTEGRATION.md](INTEGRATION.md) documents
the protocol for building the voice client into your own product.

## Run

Install this checkout and the speech dependencies in your cookbook environment:

```bash
uv pip install --python .venvs/demo/bin/python -e "libs/agno[os,voice]"
```

On Windows use `.venvs/demo/Scripts/python.exe` instead of `.venvs/demo/bin/python`.
The first voice connection loads the Silero model and can take longer than later
connections. Set your provider keys before starting:

```bash
export OPENAI_API_KEY="..."
export CARTESIA_API_KEY="..."
.venvs/demo/bin/python cookbook/05_agent_os/28_voice_pipe/voice_agent.py
```

PowerShell:

```powershell
$env:OPENAI_API_KEY = "..."
$env:CARTESIA_API_KEY = "..."
.venvs/demo/Scripts/python.exe cookbook/05_agent_os/28_voice_pipe/voice_agent.py
```

AgentOS now serves the voice pipe at `ws://localhost:7777/voice/assistant/pipe`.

## Test client

In a second terminal, serve `client/` on port 3000:

```bash
python -m http.server 3000 --bind 127.0.0.1 --directory cookbook/05_agent_os/28_voice_pipe/client
```

Open <http://localhost:3000/?pipe=assistant> (use `localhost`, not `127.0.0.1`,
which AgentOS does not allow as an origin), start a conversation, and allow
microphone access. Use the sidebar to change the AgentOS URL or the voice pipe ID
(`assistant`, `tools`, `knowledge`, `reasoning`, or `computer`), so one client serves every example. AgentOS
already allows `http://localhost:3000` as a CORS origin. To serve the client from
another origin, add it to `AgentOS(cors_allowed_origins=[...])`. Opening
`index.html` directly from disk does not work, because the browser sends
`Origin: null`.

The client provides a microphone selector, mute and end controls, live
transcripts, and expandable response timing. Audio is sent to your configured
speech providers while connected. Remote microphone access requires HTTPS.

Run the client's playback regression tests with
`node --test cookbook/05_agent_os/28_voice_pipe/client/voice-client.test.mjs`.

`VOICE_AGENT_MODEL` selects an OpenAI Responses model; the example uses
`gpt-5.6-luna` with reasoning disabled by default. Choose a model available to your
account that supports `reasoning_effort="none"`, or adjust that parameter for your
model. `CARTESIA_VOICE_ID` overrides the default Skylar voice. No API keys are sent
to the browser. If AgentOS authentication is enabled, enter its access token when
the client requests it.

Validate route registration without making provider calls:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/28_voice_pipe/voice_agent.py --check
```

## Standalone examples

Each file creates its own agent and voice server. Every agent has a SQLite db in the
repository's `tmp/` folder, so each voice turn is saved as a run and appears in
AgentOS sessions. Stop the previous example with
Ctrl+C before running another: they all use port 7777. They use the same provider
environment variables and the same test client; switch the pipe ID in the client.

| File | Feature | Voice pipe | Client URL | Try saying |
| --- | --- | --- | --- | --- |
| `voice_agent.py` | Basic conversation | `/voice/assistant/pipe` | `http://localhost:3000/?pipe=assistant` | "What can you do?" |
| `voice_tools.py` | Agno calculator and web search toolkits | `/voice/tools/pipe` | `http://localhost:3000/?pipe=tools` | "What is twelve point five times three?" |
| `voice_knowledge.py` | Answer from the Agno docs with Agno Knowledge | `/voice/knowledge/pipe` | `http://localhost:3000/?pipe=knowledge` | "What is AgentOS?" |
| `voice_reasoning.py` | Native model reasoning before each answer | `/voice/reasoning/pipe` | `http://localhost:3000/?pipe=reasoning` | "A bat and a ball cost one dollar ten..." |
| `voice_computer_use.py` | The pyautogui computer use agent, by voice | `/voice/computer/pipe` | `http://localhost:3000/?pipe=computer` | "Open Chrome and go to agno dot com" |

From the repository root, using the existing Windows development environment:

```powershell
.\.venv\Scripts\python.exe .\cookbook\05_agent_os\28_voice_pipe\voice_tools.py
```

Open <http://localhost:3000/?pipe=tools>. The agent uses Agno's built-in
`CalculatorTools` and `WebSearchTools`. Ask "What is the latest news about the James
Webb telescope?" and interrupt during the search to exercise cancellation. Web
search uses DuckDuckGo through the `ddgs` package, so no extra key is needed. The
voice pipeline does not automatically speak filler during a tool call.

For knowledge, run:

```powershell
.\.venv\Scripts\python.exe .\cookbook\05_agent_os\28_voice_pipe\voice_knowledge.py
```

Open <http://localhost:3000/?pipe=knowledge> after loading finishes. The script
loads <https://docs.agno.com/llms.txt> into a local LanceDB table in
`tmp/voice_knowledge` using OpenAI embeddings. The first run takes a while; later
runs skip content that already exists. LanceDB runs inside Python, with no database
server required. A fresh environment needs `pip install lancedb` in addition to the
voice dependencies. Try "How do I give an agent memory?" and "What is the difference
between a team and a workflow?"

`voice_reasoning.py` uses the model's native reasoning: `reasoning_effort` defaults
to `low` and `VOICE_REASONING_EFFORT` raises it. Reasoning summaries are stored on
each run for AgentOS and are never spoken. Expect more delay before the first word
than the other examples, growing with effort.

`voice_computer_use.py` imports the agent from
`cookbook/91_tools/computer_use/computer_use_agent.py` and needs `pip install
pyautogui`. It really controls your mouse and keyboard: move the mouse into a
screen corner to abort. Speaking while it works cancels the task, and the window it
minimizes first is usually the client's browser window, which keeps the call
running.

Both new scripts support `--check` without provider calls. The tools check covers
toolkit registration, local calculator calls, and routes. The knowledge check covers configuration
and routes; it does not create embeddings or test live retrieval.

## API

```python
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt.openai import OpenAIRealtimeSTT
from agno.voice.tts.cartesia import CartesiaTTS
from agno.voice.vad.silero import SileroVAD

voice = VoicePipe(
    id="assistant",
    agent=agent,  # An existing Agno Agent with a streaming model.
    vad=SileroVAD(min_silence_duration_ms=320),
    stt_model=OpenAIRealtimeSTT(language="en"),
    tts_model=CartesiaTTS(voice="db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"),
)
agent_os = AgentOS(agents=[agent], live_sockets=[voice])
app = agent_os.get_app()  # Adds the WebSocket route /voice/assistant/pipe.
```

`GET /voice` lists the registered pipes and their agents. See
[INTEGRATION.md](INTEGRATION.md) for discovery and the wire protocol: authentication, audio
framing, events, and the playback acknowledgments a client must send.

The default STT model is `gpt-live-transcribe`; audio streams over its persistent
connection while you speak. English recognition is explicit in this example, and
the agent also has an English response instruction. Cartesia `sonic-3.6` accepts
incremental text over a persistent WebSocket and returns PCM audio as it generates.
Provider configuration is reusable; each browser connection gets its own active
speech-provider and VAD state.

For an OpenAI-only setup with your existing `OPENAI_API_KEY`, select the included
`OpenAITTS` adapter without changing the code:

```bash
VOICE_TTS_PROVIDER=openai .venvs/demo/bin/python cookbook/05_agent_os/28_voice_pipe/voice_agent.py
```

PowerShell:

```powershell
$env:VOICE_TTS_PROVIDER = "openai"
.venvs/demo/Scripts/python.exe cookbook/05_agent_os/28_voice_pipe/voice_agent.py
```

This path does not require `CARTESIA_API_KEY`. `OpenAITTS` buffers bounded text
phrases and streams each resulting audio response; its speech endpoint does not
accept a live text stream. Cartesia remains the default for incremental text input.
The two TTS paths have different startup latency characteristics.

## How audio flows

```text
Browser AudioWorklet ── PCM16, 24 kHz ──► /voice/{id}/pipe
                                            ├─► Silero VAD (16 kHz internally)
                                            └─► Streaming STT
                                                     │ partial/final transcript
                                                     ▼
                                                Agent.arun(stream=True)
                                                     │ text deltas
                                                     ▼
                                                Streaming TTS
Browser scheduled playback ◄── PCM + reply ID ────────┘
```

The browser sends fixed 32 ms microphone frames. The backend keeps transcription
running during speech, commits a turn after the configured silence interval, and
forwards the agent's text stream to TTS. Reply IDs prevent delayed audio from an
interrupted answer from playing. Playback acknowledgments report samples that have
reached the browser's output clock, so queued audio is not counted as heard.

The displayed assistant transcript contains generated text and can extend beyond
what played during an interrupted reply. Such replies are labeled in the UI.
Clearing the display removes transcript rows from the page; it does not reset an
active conversation. End and restart the conversation to open a fresh voice session.

Audio delivery follows browser playback acknowledgments. By default, the server
sends at most two seconds ahead, so fast speech generation cannot fill the browser
with an entire long answer at once. `max_playback_buffer_seconds` controls that
window, and `playback_timeout` defaults to 15 seconds without playback progress
while the window is full. The browser retains a separate 30-second hard limit on
unplayed samples. Its limit counts actual audio, excluding time spent connecting
or waiting for a reply. `response_timeout` still limits the whole response to 60
seconds by default, including time spent delivering paced audio.

After updating this checkout, restart the Python server and hard-refresh the test
client (Ctrl+F5 on Windows) to load the matching browser code.

## Measure before tuning

The timing panel reports final transcript, first token, first audio sent, and
estimated playback relative to detected speech end. The configured silence window
occurs before that reference point. Browser output timing is an estimate; hardware
and network conditions still matter. No end-to-end latency target is guaranteed.

Try the same utterance several times, including "What are you and what can you do?",
and compare the transcript to what you said. Then test a pause mid-sentence,
interruption during a long reply, mute and unmute, microphone disconnection, and a
slow tool. Separate initial provider/model warm-up from subsequent turns when
comparing results. A VAD-only silence threshold can still end a turn too early;
semantic turn detection is a future extension.

This first implementation uses WebSockets, browser echo cancellation, and local
Silero VAD. WebRTC, resumable calls, and a background reasoning agent are outside
this example. Agent tools retain their normal streaming behavior; this wrapper
does not automatically create a background thinker or invent filler speech.
