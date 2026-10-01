# Voice pipe protocol

AgentOS exposes each `VoicePipe` in `live_sockets` at a single WebSocket route:

```text
/voice/{id}/pipe
```

It also lists the registered pipes at `GET /voice`. AgentOS does not serve a voice
page or browser assets. Your product owns the
client. `client/` in this folder is a reference implementation of everything below:
`voice-client.js` handles the socket and playback, and `audio-worklet.js` handles
microphone capture.

## Server setup

```python
agent_os = AgentOS(
    agents=[agent],
    live_sockets=[VoicePipe(id="support", agent=agent, vad=..., stt_model=..., tts_model=...)],
    # Browser pages served from another origin must be listed explicitly.
    cors_allowed_origins=["https://app.example.com"],
)
```

Clients then connect to `wss://<your-agentos-host>/voice/support/pipe`.

## Discovery

`GET /voice` returns each pipe and the agent it speaks for:

```json
[
  {"id": "support", "agent_id": "support-agent", "agent_name": "Support", "path": "/voice/support/pipe"}
]
```

Use `path` to open the socket and `agent_id` to load that agent's saved voice
sessions from `/sessions`. The endpoint uses normal AgentOS HTTP authentication
and appears in `/docs`; the WebSocket itself does not, because OpenAPI cannot
describe WebSocket routes. Like `GET /agents`, it only lists pipes whose agent the
caller can read. A server without live sockets returns 404.

## Connection rules

- **Origin.** A connection with no `Origin` header (a server or native app) is
  allowed. A browser `Origin` is allowed when it matches the AgentOS host, or when it
  appears exactly in `cors_allowed_origins`. Wildcards never apply to voice, so other
  websites cannot spend your speech credentials. Pages opened from disk send
  `Origin: null` and are always rejected.
- **Unknown pipe or rejected origin.** The handshake is refused with HTTP 403.
  Browsers report this as a connection error with close code `1006`, the same as
  an unreachable server.
- **Sessions.** Each connection gets a fresh, server-generated agent session.
  Client-supplied `user_id` and `session_id` values are ignored.

## Authentication

When AgentOS has no security key, JWT or service accounts configured, the server
sends `ready` immediately. Otherwise, authenticate in one of two ways:

1. **Header (non-browser clients).** Send `Authorization: Bearer <token>` on the
   WebSocket upgrade request.
2. **First message (browsers, which cannot set upgrade headers).** The server sends
   `{"event": "auth_required"}`. Within 10 seconds, reply with:

   ```json
   {"action": "authenticate", "token": "<token>"}
   ```

On success the server sends `{"event": "authenticated", "user_id": "..."}`, then
opens the speech providers. On failure it sends
`{"event": "auth_error", "error": "..."}` and closes with `1008`. A scoped token must
be allowed to run the pipe's agent.

Do not ship your AgentOS security key to browsers. Have your backend issue each
user a short-lived JWT or a scoped service-account token.

Authentication messages use an `event` key. All later messages use `type`.

## Audio format

| Direction | Format |
| --- | --- |
| Client to server | Binary frames of exactly 768 samples of PCM16 little-endian, mono, 24 kHz (1,536 bytes, 32 ms) |
| Server to client | Binary frames with an 8-byte header, then PCM16 little-endian, mono, 24 kHz |

Server audio header, both values `uint32` little-endian:

| Bytes | Field |
| --- | --- |
| 0-3 | `reply_id` |
| 4-7 | Sample offset of this chunk within the reply |

A frame of any other size closes the session. Stream microphone audio continuously
after `ready`, including silence; the server detects speech itself. Enable echo
cancellation in the browser so the agent does not hear itself.

## Server messages

| `type` | Fields | Meaning |
| --- | --- | --- |
| `ready` | `pipe_id`, `session_id`, `sample_rate`, `frame_samples` | Providers are connected. Start streaming microphone frames. |
| `speech_started` | `turn_id` | The user started talking. Stop playback immediately. |
| `speech_stopped` | `turn_id` | Silence detected; the turn is being transcribed. |
| `transcript_delta` | `turn_id`, `text` | Partial transcript (replaces the previous partial). |
| `transcript` | `turn_id`, `text` | Final transcript for the turn. |
| `reply_started` | `reply_id` | A new agent reply begins. Discard audio from older replies. |
| `assistant_delta` | `reply_id`, `text` | Streamed reply text (append). |
| `assistant_complete` | `reply_id`, `text` | Full reply text. |
| `tool_started` / `tool_completed` | `reply_id`, `name` | The agent is running a tool. |
| `reply_done` | `reply_id` | No more audio for this reply. |
| `stop_playback` | `reply_id` | The reply was interrupted. Drop its queued audio. |
| `listening` | | Waiting for the user. |
| `metric` | `reply_id`, `name`, `ms` | Latency from speech end: `transcript_final`, `first_token`, `first_audio_sent`, `total_to_playback`. |
| `pong` | | Reply to `ping`. |
| `error` | `fatal`, `message` | When `fatal` is true, the server closes the socket. |

## Client messages

JSON text frames of at most 4,096 characters:

| `type` | Fields | When |
| --- | --- | --- |
| `playback_started` | `reply_id` | The first sample of a reply actually plays. |
| `played` | `reply_id`, `samples` | Cumulative samples of the reply that have reached the speaker. Send about every 100 ms. |
| `ping` | | Optional keepalive. |
| `stop` | | End the session. |

## Playback acknowledgments are required

The server sends at most `max_playback_buffer_seconds` (2 seconds by default) of
audio beyond the last `played` count. If your client never acknowledges, the reply
stalls and fails after `playback_timeout` (15 seconds by default).

Acknowledgments also decide conversation history: when the user interrupts, the
agent remembers only the text that was actually heard. Count samples that have
played from your output clock, not samples you have received or scheduled.

## Minimal client loop

1. Open the socket and handle `auth_required` if your AgentOS requires auth.
2. On `ready`, start sending 768-sample PCM16 frames from the microphone.
3. On `reply_started`, create a playback queue for that `reply_id`.
4. On binary audio, check that `reply_id` matches the current reply and the offset
   continues the previous chunk, then schedule it for playback.
5. While audio plays, send `playback_started` once, then `played` regularly.
6. On `speech_started` or `stop_playback`, stop and clear playback right away.
7. Send `{"type": "stop"}` and close the socket when the user ends the call.
