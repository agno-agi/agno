// Run with: node --test cookbook/05_agent_os/28_voice_pipe/client/voice-client.test.mjs
// Exercise the shipped browser code with deterministic audio clocks; no providers.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const clientUrl = new URL("./voice-client.js", import.meta.url);
const source = readFileSync(clientUrl, "utf8").replaceAll("import.meta.url", JSON.stringify(clientUrl.href));

function setup({ currentTime = 0, presentationTime = null } = {}) {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      textContent: "", hidden: true, dataset: {}, style: {}, attributes: {},
      addEventListener() {}, setAttribute(key, value) { this.attributes[key] = value; },
      querySelector() { return null; },
    });
    return elements.get(id);
  };
  const sent = [];
  const scheduled = [];
  const clock = { performanceTime: 100000, presentationTime };
  const context = {
    currentTime, baseLatency: 0.01, outputLatency: 0.01, state: "running",
    getOutputTimestamp() {
      return { contextTime: clock.presentationTime ?? Math.max(0, this.currentTime - 0.02), performanceTime: clock.performanceTime };
    },
    createBuffer(channels, samples) {
      const data = new Float32Array(samples);
      return { getChannelData() { return data; } };
    },
    createBufferSource() {
      const node = { connect() {}, disconnect() {}, stop() { node.stopped = true; }, start(at) { node.at = at; } };
      scheduled.push(node);
      return node;
    },
    close() { this.state = "closed"; return Promise.resolve(); },
  };
  const call = {
    ready: true, muted: false, hearing: false, sampleRate: 24000, context,
    socket: { readyState: 1, send(value) { sent.push(JSON.parse(value)); }, close() {} },
  };
  const sandbox = vm.createContext({
    URL, URLSearchParams, DataView, ArrayBuffer, Float32Array, setTimeout, clearTimeout, setInterval, clearInterval,
    performance: { now: () => 100000 }, WebSocket: { OPEN: 1 },
    location: { pathname: "/", search: "", href: "http://localhost:3000/", origin: "http://localhost:3000", protocol: "http:" },
    document: { getElementById: element, querySelectorAll: () => [] },
    window: { addEventListener() {} }, navigator: {},
  });
  vm.runInContext(source + "\nglobalThis.client = { audio, acknowledge, stopPlayback, event, state, attach(call) { session = call; } };", sandbox);
  const client = sandbox.client;
  client.attach(call);
  client.event(call, { type: "reply_started", reply_id: 1 });
  return { client, call, context, clock, sent, scheduled, element };
}

function packet(samples, offset = 0, id = 1) {
  const bytes = new ArrayBuffer(8 + samples * 2);
  const header = new DataView(bytes);
  header.setUint32(0, id, true);
  header.setUint32(4, offset, true);
  return bytes;
}

test("first short audio after a long wait does not look like a full buffer", () => {
  const fixture = setup({ currentTime: 90, presentationTime: 0.1 });
  const { client, call, context, scheduled, element } = fixture;
  client.audio(call, packet(2400));
  assert.equal(element("error").hidden, true);
  assert.equal(scheduled.length, 1);
  assert.equal(call.reply.played, 0, "scheduled speech must not count as heard");
  context.currentTime = 90.075;
  client.acknowledge(call);
  assert.ok(call.reply.played > 0 && call.reply.played < 2400);
});

test("current device timestamp controls partial playback and interruption", () => {
  const { client, call, context, clock, sent, scheduled } = setup({ currentTime: 10, presentationTime: 9.98 });
  client.audio(call, packet(12000));
  context.currentTime = 10.3;
  clock.presentationTime = 10.225;
  client.stopPlayback(call, true);
  const played = sent.filter((event) => event.type === "played").at(-1).samples;
  assert.ok(Math.abs(played - 4800) <= 1);
  assert.ok(scheduled.every((node) => node.stopped));
  client.audio(call, packet(2400, 12000));
  assert.equal(scheduled.length, 1, "late audio from interrupted reply is discarded");
});

test("uninitialized or old performance timestamps use the latency-adjusted clock", () => {
  const { client, call, context, clock } = setup({ currentTime: 2, presentationTime: 0 });
  client.audio(call, packet(2400));
  context.currentTime = 2.095;
  clock.presentationTime = 2.09;
  clock.performanceTime = 1000;
  client.acknowledge(call);
  assert.ok(Math.abs(call.reply.played - 1200) <= 1);
});

test("an ahead-of-context timestamp cannot acknowledge future scheduled audio", () => {
  const { client, call } = setup({ currentTime: 5, presentationTime: 500 });
  client.audio(call, packet(2400));
  client.acknowledge(call);
  assert.equal(call.reply.played, 0);
});

test("a forty-second reply can stream through a small moving playback window", () => {
  const { client, call, context, element } = setup();
  for (let index = 0; index < 400; index++) {
    client.audio(call, packet(2400, index * 2400));
    assert.equal(element("error").hidden, true);
    assert.ok(call.reply.receivedSamples - call.reply.played <= 2.1 * 24000);
    if ((index + 1) % 20 === 0) {
      context.currentTime += 2;
      client.acknowledge(call);
    }
  }
  context.currentTime += 0.1;
  client.event(call, { type: "reply_done", reply_id: 1 });
  assert.equal(call.reply.played, 40 * 24000);
  assert.equal(call.reply.chunks.length, 0);
});

test("a genuinely oversized unplayed burst is rejected before allocation", () => {
  const { client, call, scheduled, element } = setup();
  client.audio(call, packet(31 * 24000));
  assert.equal(scheduled.length, 0);
  assert.match(element("error").textContent, /more audio than playback could accept/);
  assert.equal(call.ready, false);
});

test("audio offsets cannot duplicate speech or skip unheard samples", () => {
  const { client, call, scheduled, element } = setup();
  client.audio(call, packet(2400));
  client.audio(call, packet(2400, 0));
  assert.equal(scheduled.length, 1);
  assert.match(element("error").textContent, /lost its place/);
});

test("loading state exposes busy status and clears when listening", () => {
  const { client, element } = setup();
  for (const state of ["connecting", "thinking"]) {
    client.state(state, "Working", "Please wait");
    assert.equal(element("call").attributes["aria-busy"], "true");
  }
  client.state("listening", "Listening", "Go ahead");
  assert.equal(element("call").attributes["aria-busy"], "false");
});
