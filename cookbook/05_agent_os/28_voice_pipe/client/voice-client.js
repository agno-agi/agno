const element = (id) => document.getElementById(id);
const ui = {
  call: element("call"), button: element("call-button"), mute: element("mute-button"),
  status: element("status"), hint: element("hint"), connection: element("connection"),
  device: element("device"), messages: element("messages"), error: element("error"),
  server: element("server"), pipe: element("pipe"),
};
const workletUrl = new URL("./audio-worklet.js", import.meta.url);
const MAX_TRANSCRIPT_ROWS = 200;
const MAX_QUEUED_AUDIO_SECONDS = 30;
const rows = new Map();
let session = null;
let sessionNumber = 0;

// ?server=http://localhost:7777&pipe=tools preselects a connection.
const query = new URLSearchParams(location.search || "");
if (query.get("server")) ui.server.value = query.get("server");
if (query.get("pipe")) ui.pipe.value = query.get("pipe");

// Every AgentOS live socket is served at /voice/{id}/ws.
function pipeUrl() {
  const id = (ui.pipe.value || "").trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(id)) throw new Error("Enter a voice pipe ID, such as assistant.");
  let url;
  try {
    url = new URL(`voice/${id}/ws`, (ui.server.value || "").trim().replace(/\/*$/, "/"));
  } catch {
    throw new Error("Enter the AgentOS URL, such as http://localhost:7777.");
  }
  if (url.protocol === "http:") url.protocol = "ws:";
  else if (url.protocol === "https:") url.protocol = "wss:";
  else if (url.protocol !== "ws:" && url.protocol !== "wss:") throw new Error("The AgentOS URL must start with http or https.");
  return url;
}

function state(name, title, hint) {
  ui.call.dataset.state = name;
  ui.call.setAttribute("aria-busy", String(name === "connecting" || name === "thinking"));
  ui.status.textContent = title;
  ui.hint.textContent = hint;
}

function error(message) {
  ui.error.textContent = message;
  ui.error.hidden = !message;
}

function send(call, event) {
  if (call.socket?.readyState === WebSocket.OPEN) call.socket.send(JSON.stringify(event));
}

function showListening(call) {
  if (call !== session || !call.ready || call.reply?.chunks.length || call.hearing) return;
  state("listening", call.muted ? "Microphone muted" : "I'm listening", call.muted ? "Unmute to continue the conversation." : "Speak naturally. You can interrupt any reply.");
}

function message(role, id, text, { append = false, partial = false } = {}) {
  const key = `${sessionNumber}:${role}:${id}`;
  const nearBottom = ui.messages.scrollHeight - ui.messages.scrollTop - ui.messages.clientHeight < 90;
  element("empty")?.remove();
  let row = rows.get(key);
  if (!row) {
    row = document.createElement("article");
    row.className = "message";
    row.dataset.role = role;
    const label = document.createElement("div");
    label.className = "message-label";
    label.textContent = role === "user" ? "You" : "Assistant";
    row.append(label, document.createElement("p"));
    ui.messages.append(row);
    rows.set(key, row);
    while (rows.size > MAX_TRANSCRIPT_ROWS) {
      const oldest = rows.keys().next().value;
      rows.get(oldest).remove();
      rows.delete(oldest);
    }
  }
  row.dataset.partial = String(partial);
  const paragraph = row.querySelector("p");
  paragraph.textContent = append ? paragraph.textContent + text : text;
  if (nearBottom) ui.messages.scrollTop = ui.messages.scrollHeight;
  return row;
}

function outputTime(call) {
  if (!call.context) return 0;
  const now = call.context.currentTime;
  const latency = (call.context.baseLatency || 0) + (call.context.outputLatency || 0);
  const timestamp = call.context?.getOutputTimestamp?.();
  // Some devices report an old timestamp during startup or after suspension.
  // Use the presentation clock only while it agrees with the running context.
  const fresh = timestamp && Number.isFinite(timestamp.contextTime) && timestamp.contextTime > 0
    && timestamp.contextTime <= now
    && now - timestamp.contextTime <= Math.max(1, latency + 0.25)
    && Number.isFinite(timestamp.performanceTime)
    && Math.abs(performance.now() - timestamp.performanceTime) <= 1000;
  const clock = fresh ? timestamp.contextTime : Math.max(0, now - latency);
  call.outputClock = Math.max(call.outputClock || 0, clock);
  return call.outputClock;
}

function acknowledge(call) {
  const reply = call.reply;
  if (!reply || !call.context) return;
  const clock = outputTime(call);
  for (const chunk of reply.chunks) {
    const played = Math.max(0, Math.min(chunk.samples, Math.floor((clock - chunk.at) * call.sampleRate)));
    if (played > 0) reply.played = Math.max(reply.played, chunk.offset + played);
  }
  if (!reply.started && reply.played > 0) {
    reply.started = true;
    send(call, { type: "playback_started", reply_id: reply.id });
    state("speaking", "Speaking", "Go ahead and interrupt if you need to.");
  }
  if (reply.played > reply.acknowledged) {
    send(call, { type: "played", reply_id: reply.id, samples: reply.played });
    reply.acknowledged = reply.played;
  }
  reply.chunks = reply.chunks.filter((chunk) => clock < chunk.at + chunk.samples / call.sampleRate);
  if (!reply.chunks.length && reply.done) showListening(call);
}

function stopPlayback(call, interrupted = false) {
  acknowledge(call);
  if (!call.reply) return;
  if (interrupted && (!call.reply.done || call.reply.chunks.length)) {
    const row = rows.get(`${sessionNumber}:assistant:${call.reply.id}`);
    if (row && !row.querySelector("small")) {
      const note = document.createElement("small");
      note.textContent = "Interrupted · some generated text may not have been spoken";
      row.append(note);
    }
  }
  for (const chunk of call.reply.chunks) {
    try { chunk.source.stop(); } catch { /* The node may have already ended. */ }
    chunk.source.disconnect();
  }
  call.reply = null;
}

function audio(call, bytes) {
  if (call !== session || !call.ready || bytes.byteLength < 10 || bytes.byteLength % 2) return;
  const view = new DataView(bytes);
  const id = view.getUint32(0, true);
  const offset = view.getUint32(4, true);
  const reply = call.reply;
  if (!reply || reply.id !== id) return; // Ignore output from an interrupted generation.
  acknowledge(call);
  const samples = (bytes.byteLength - 8) / 2;
  if (offset !== reply.receivedSamples) {
    error("The audio stream lost its place. Reconnect to try again.");
    stop(call);
    return;
  }
  const at = Math.max(reply.nextAt, call.context.currentTime + 0.025);
  const endAt = at + samples / call.sampleRate;
  // Bound actual audio, not the distance between two potentially stale clocks.
  // The server normally sends at most two seconds ahead of playback.
  if (reply.receivedSamples + samples - reply.played > MAX_QUEUED_AUDIO_SECONDS * call.sampleRate) {
    error("The server sent more audio than playback could accept. Reconnect to try again.");
    stop(call);
    return;
  }
  const buffer = call.context.createBuffer(1, samples, call.sampleRate);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < samples; i++) channel[i] = view.getInt16(8 + i * 2, true) / 32768;
  const source = call.context.createBufferSource();
  source.buffer = buffer;
  source.connect(call.context.destination);
  reply.receivedSamples += samples;
  reply.nextAt = endAt;
  reply.chunks.push({ source, at, offset, samples });
  source.onended = () => source.disconnect();
  source.start(at);
}

async function ready(call, event) {
  if (call !== session || call.ready) return;
  if (event.sample_rate !== 24000 || event.frame_samples !== 768) {
    throw new Error("Unsupported voice audio format.");
  }
  call.sampleRate = event.sample_rate;
  call.capture = new AudioWorkletNode(call.context, "voice-capture", {
    numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
    processorOptions: { sampleRate: event.sample_rate, frameSamples: event.frame_samples },
  });
  call.capture.port.onmessage = ({ data }) => {
    if (call !== session || !call.ready || call.socket.readyState !== WebSocket.OPEN) return;
    if (call.socket.bufferedAmount > 96000) {
      error("The audio connection cannot keep up. Check your connection, then try again.");
      stop(call);
      return;
    }
    call.socket.send(data.pcm);
    const intensity = call.muted ? 0 : Math.min(1, data.level * 8);
    document.querySelectorAll(".wave i").forEach((bar, index) => {
      const envelope = 1 - Math.abs(index - 4) / 6;
      bar.style.height = `${12 + intensity * envelope * 42}px`;
    });
  };
  call.capture.onprocessorerror = () => {
    error("Microphone processing stopped. Start a new conversation to reconnect.");
    stop(call);
  };
  call.source = call.context.createMediaStreamSource(call.stream);
  call.source.connect(call.capture);
  call.capture.connect(call.context.destination); // The worklet emits silence.
  call.ready = true;
  clearTimeout(call.timeout);
  call.ackTimer = setInterval(() => acknowledge(call), 100);
  ui.connection.textContent = "Connected";
  ui.connection.dataset.connected = "true";
  ui.mute.disabled = false;
  element("auth").hidden = true;
  showListening(call);
}

async function event(call, data) {
  if (call !== session) return;
  const kind = data.type || data.event;
  switch (kind) {
    case "auth_required": {
      const token = element("token").value.trim();
      if (token) send(call, { action: "authenticate", token });
      else {
        element("auth").hidden = false;
        element("token").focus();
        state("auth", "Authentication required", "Enter your AgentOS access token below to connect.");
      }
      break;
    }
    case "authenticated":
      element("auth").hidden = true;
      state("connecting", "Getting ready", "Opening the speech connection…");
      break;
    case "ready":
      await ready(call, data);
      break;
    case "speech_started":
      stopPlayback(call, true);
      call.hearing = true;
      document.querySelectorAll(".metrics dd").forEach((value) => { value.textContent = "—"; });
      state("hearing", "I hear you", "Take your time. I'm listening.");
      break;
    case "speech_stopped":
      call.hearing = false;
      state("thinking", "Thinking", "Putting a reply together…");
      break;
    case "transcript_delta":
      message("user", data.turn_id, data.text, { partial: true });
      break;
    case "transcript":
      message("user", data.turn_id, data.text);
      break;
    case "reply_started":
      stopPlayback(call);
      call.reply = { id: data.reply_id, nextAt: 0, receivedSamples: 0, played: 0, acknowledged: 0, started: false, done: false, chunks: [] };
      state("thinking", "Thinking", "Putting a reply together…");
      break;
    case "assistant_delta":
      if (call.reply?.id === data.reply_id) message("assistant", data.reply_id, data.text, { append: true });
      break;
    case "assistant_complete":
      if (call.reply?.id === data.reply_id) message("assistant", data.reply_id, data.text);
      break;
    case "reply_done":
      if (call.reply?.id === data.reply_id) {
        call.reply.done = true;
        acknowledge(call);
      }
      break;
    case "stop_playback":
      if (data.reply_id == null || call.reply?.id === data.reply_id) stopPlayback(call, true);
      break;
    case "listening":
      call.hearing = false;
      showListening(call);
      break;
    case "tool_started":
      ui.hint.textContent = "Checking something for you…";
      break;
    case "tool_completed":
      ui.hint.textContent = "Putting a reply together…";
      break;
    case "metric": {
      const metric = element(`metric-${data.name}`);
      if (metric && Number.isFinite(data.ms)) metric.textContent = `${Math.round(data.ms)} ms`;
      break;
    }
    case "error":
    case "auth_error":
      error(data.message || data.error || "The voice connection encountered an error.");
      if (data.fatal) stop(call);
      else showListening(call);
      break;
  }
}

async function devices() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const selected = ui.device.value;
  const list = await navigator.mediaDevices.enumerateDevices();
  ui.device.replaceChildren(new Option("System default", ""));
  list.filter((device) => device.kind === "audioinput" && device.deviceId && device.deviceId !== "default").forEach((device, index) => {
    ui.device.add(new Option(device.label || `Microphone ${index + 1}`, device.deviceId));
  });
  if ([...ui.device.options].some((option) => option.value === selected)) ui.device.value = selected;
}

async function start() {
  error("");
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    error("Microphone access requires HTTPS or localhost in a supported browser.");
    return;
  }
  if (!window.AudioContext || !window.AudioWorkletNode) {
    error("This browser does not support audio worklets. Use a current Chrome, Edge, Firefox, or Safari release.");
    return;
  }
  let url;
  try {
    url = pipeUrl();
  } catch (cause) {
    error(cause.message);
    return;
  }
  try {
    const params = new URLSearchParams({ server: ui.server.value.trim(), pipe: ui.pipe.value.trim() });
    history.replaceState(null, "", `${location.pathname}?${params}`);
  } catch { /* Keeping the selection in the address bar is optional. */ }
  const call = { ready: false, muted: false, hearing: false, reply: null, sampleRate: 24000 };
  session = call;
  sessionNumber++;
  element("call-button-label").textContent = "End conversation";
  ui.button.dataset.active = "true";
  ui.device.disabled = true;
  ui.server.disabled = true;
  ui.pipe.disabled = true;
  ui.connection.textContent = "Connecting";
  state("connecting", "Getting ready", "Allow microphone access to start the conversation.");
  try {
    // Resume inside the click gesture, before permissions or networking can delay it.
    try {
      call.context = new AudioContext({ latencyHint: "interactive", sampleRate: 24000 });
    } catch {
      // Browsers limited to the device sample rate use the worklet's resampler.
      call.context = new AudioContext({ latencyHint: "interactive" });
    }
    await call.context.resume();
    if (call !== session) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: {
      channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
      ...(ui.device.value ? { deviceId: { exact: ui.device.value } } : {}),
    } });
    if (call !== session) { stream.getTracks().forEach((track) => track.stop()); return; }
    call.stream = stream;
    stream.getAudioTracks()[0].onended = () => {
      if (session !== call) return;
      error("The microphone was disconnected. Select a microphone and reconnect.");
      stop(call);
    };
    await call.context.audioWorklet.addModule(workletUrl);
    if (call !== session) return;
    void devices().catch(() => {});
    state("connecting", "Getting ready", "Opening the speech connection…");
    call.socket = new WebSocket(url);
    call.socket.binaryType = "arraybuffer";
    call.socket.onmessage = ({ data }) => {
      if (data instanceof ArrayBuffer) audio(call, data);
      else {
        try {
          void event(call, JSON.parse(data)).catch(() => {
            error("Could not start the audio stream. Reconnect to try again.");
            stop(call);
          });
        } catch {
          error("The server sent an invalid voice event.");
          stop(call);
        }
      }
    };
    call.socket.onclose = ({ code }) => {
      if (session !== call) return;
      if (code !== 1000 && !ui.error.textContent) error("The voice connection closed. Check the server and reconnect.");
      stop(call);
    };
    call.socket.onerror = () => {
      // Browsers cannot tell a stopped server from a rejected handshake.
      if (session === call && !call.ready) error(`Could not connect to ${url}. Check that AgentOS is running, that the voice pipe ID exists, and that AgentOS allows this page's origin (${location.origin}).`);
    };
    call.timeout = setTimeout(() => {
      if (call !== session || call.ready) return;
      error("The voice connection took too long to start. Check provider credentials and the server logs.");
      stop(call);
    }, 60000);
  } catch (cause) {
    if (session !== call) return;
    error(cause.name === "NotAllowedError" ? "Microphone access was denied. Allow it in your browser's site settings, then reconnect." : cause.name === "NotFoundError" ? "No microphone was found. Connect a microphone and try again." : `Could not start voice: ${cause.message}`);
    stop(call);
  }
}

function stop(call = session) {
  if (!call) return;
  clearTimeout(call.timeout);
  clearInterval(call.ackTimer);
  stopPlayback(call);
  send(call, { type: "stop" });
  call.ready = false;
  call.socket?.close(1000);
  call.capture?.disconnect();
  call.source?.disconnect();
  call.stream?.getTracks().forEach((track) => { track.onended = null; track.stop(); });
  if (call.context?.state !== "closed") void call.context?.close().catch(() => {});
  if (session !== call) return;
  session = null;
  element("call-button-label").textContent = "Start conversation";
  ui.button.dataset.active = "false";
  ui.mute.disabled = true;
  ui.mute.setAttribute("aria-pressed", "false");
  ui.mute.setAttribute("aria-label", "Mute microphone");
  ui.mute.title = "Mute microphone";
  element("mute-slash").setAttribute("hidden", "");
  ui.device.disabled = false;
  ui.server.disabled = false;
  ui.pipe.disabled = false;
  ui.connection.textContent = "Not connected";
  ui.connection.dataset.connected = "false";
  element("auth").hidden = true;
  document.querySelectorAll(".wave i").forEach((bar) => { bar.style.height = "12px"; });
  state("idle", "Ready when you are", "Start a new conversation whenever you're ready.");
}

ui.button.addEventListener("click", () => session ? stop() : void start());
ui.mute.addEventListener("click", () => {
  if (!session?.ready) return;
  session.muted = !session.muted;
  session.stream.getAudioTracks().forEach((track) => { track.enabled = !session.muted; });
  ui.mute.setAttribute("aria-pressed", String(session.muted));
  ui.mute.setAttribute("aria-label", session.muted ? "Unmute microphone" : "Mute microphone");
  ui.mute.title = session.muted ? "Unmute microphone" : "Mute microphone";
  element("mute-slash").toggleAttribute("hidden", !session.muted);
  if (ui.call.dataset.state === "listening") showListening(session);
});
element("clear-button").addEventListener("click", () => { ui.messages.replaceChildren(); rows.clear(); });
element("auth").addEventListener("submit", (submit) => {
  submit.preventDefault();
  if (session && element("token").value.trim()) send(session, { action: "authenticate", token: element("token").value.trim() });
});
window.addEventListener("pagehide", () => stop());
navigator.mediaDevices?.addEventListener("devicechange", () => { void devices().catch(() => {}); });
void devices().catch(() => {});
