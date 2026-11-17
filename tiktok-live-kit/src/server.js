// TikTok Live Kit: lõi dùng chung. Nguồn live → đường ống → WebSocket → theme (overlay) + bảng điều khiển.

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { createEngine } from './core/engine.js';
import { createSession } from './core/session.js';
import { createGiftCatalog } from './core/gift-catalog.js';
import { sanitizeRules } from './core/rules.js';
import { createManager } from './providers/manager.js';
import { createDemo } from './providers/demo.js';
import { listThemes, loadTheme, settingValues } from './themes.js';
import { createVoice, fill } from './core/voice.js';
import { setExtraWords } from './core/profanity.js';
import { createTTS } from './core/tts.js';
import { createDraws } from './core/draws.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// Repo dự án (ví dụ một kênh live) có thể dùng kit này mà để theme + dữ liệu ở chỗ riêng:
//   KIT_THEMES_DIR  thư mục theme của dự án (ưu tiên hơn themes/ của kit)
//   KIT_DATA_DIR    thư mục dữ liệu (luật đã chỉnh, phiên live, giọng đọc...)
//   KIT_CONFIG      file cấu hình của dự án (ghi đè config.json của kit)
const DATA = path.resolve(process.env.KIT_DATA_DIR || path.join(ROOT, 'data'));
const THEME_DIRS = [process.env.KIT_THEMES_DIR, path.join(ROOT, 'themes')].filter(Boolean).map((d) => path.resolve(d));
// config.json là mặc định (trong git); lựa chọn đổi lúc chạy (kênh, nguồn, theme) lưu riêng ở data/settings.json
const SETTINGS_FILE = path.join(DATA, 'settings.json');
const readJson = (f) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return {}; } };
const settings = readJson(SETTINGS_FILE);
const config = { ...readJson(path.join(ROOT, 'config.json')), ...(process.env.KIT_CONFIG ? readJson(path.resolve(process.env.KIT_CONFIG)) : {}), ...settings };
const PORT = Number(process.env.PORT || config.port || 3939);
// host: một địa chỉ hoặc danh sách ("127.0.0.1,192.168.78.191" / ["127.0.0.1", "..."]): nghe thêm đúng các địa chỉ đó
// (ví dụ đường USB tới điện thoại) mà không phải mở cả mạng như allowLan
const HOSTS = [].concat(process.env.HOST || config.host || '127.0.0.1').flatMap((h) => String(h).split(',')).map((h) => h.trim()).filter(Boolean);

// ---------- Theme, luật, phiên ----------
let theme, rules, session, engine, themeSettings;
let periodicTimer = null;
let periodicIdx = 0;
let promptTimer = null; let promptIdx = 0; let lastPromptAt = 0; let lastChatAt = 0;
const catalog = createGiftCatalog(path.join(DATA, 'gifts.json'));
const voice = createVoice();
const draws = createDraws();
const tts = createTTS({
  dir: path.join(DATA, 'tts'),
  cacheDir: path.join(DATA, 'tts-cache'),
  onReady: (r) => broadcast({ type: 'event', ev: { kind: 'tts', at: Date.now(), url: `/tts/${r.file}`, text: r.text, for: r.for || '', about: r.about || '' } }),
  onError: (msg) => { console.warn('[ses]', msg); broadcast({ type: 'error', message: msg }, 'control'); },
});

/** Đọc một câu bằng giọng của theme (nếu đang bật). */
// Câu đọc quẻ, quà, danh hiệu, mục tiêu chen lên trước; câu chào người vào, đọc bình luận chỉ đọc khi rảnh
const PRIORITY = new Set(['draw', 'gift', 'title', 'goal']);
const LOW = new Set(['join', 'chat', 'like', 'member']);
const CACHED = new Set(['draw', 'prompt', 'periodic']); // câu cố định: đọc sẵn, lần sau phát ngay
function speak(text, meta = {}) {
  if (!text || !themeSettings?.voiceEnabled) return;
  const v = theme.voice || {};
  const go = () => tts.say(text, { voice: v.voice, meta, fallback: v.fallback, priority: PRIORITY.has(meta.about), low: LOW.has(meta.about), cache: CACHED.has(meta.about) });
  // voice.delay: { "draw": 2300 } chờ cho khớp lúc hình hiện (thẻ quẻ mở sau khi lắc ống xăm)
  const wait = Number(v.delay?.[meta.about]) || 0;
  if (wait) setTimeout(go, wait); else go();
}

/** Đọc sẵn các câu cố định: đọc quẻ của mọi lá thăm (mẫu câu không có tên người), tụng kinh định kỳ, lời mời tương tác. */
function warmDraws() {
  const v = theme.voice || {};
  if (!v.enabled) return;
  const text = (x) => (typeof x === 'string' ? x : x?.speak === false ? '' : x?.say || x?.text || '');
  const texts = [...(theme.periodic?.items || []), ...(theme.prompts?.items || [])].map(text).filter(Boolean);
  const personal = ['ten', 'loi', 'chat', 'xu', 'lan', 'qua', 'danh_hieu'];
  for (const t of v.draw || []) {
    const used = [...t.matchAll(/\{(\w+)\}/g)].map((m) => m[1]);
    for (const d of Object.values(theme.draws || {})) for (const [i, it] of (d.items || []).entries()) {
      // câu còn chỗ điền tên / lời riêng của từng người (mà lá thăm không có sẵn) thì không đọc sẵn được
      if (used.some((k) => personal.includes(k) && !(k in it))) continue;
      texts.push(fill(t, { n: i + 1, ...Object.fromEntries(Object.entries(it).map(([k, x]) => [k, Array.isArray(x) ? x.join(', ') : x])) }));
    }
  }
  const n = tts.warm(texts, v.voice);
  if (n) console.log(`[ses] ${n} sabit cümle arka planda önceden seslendiriliyor`);
}

/** Mọi sự kiện đi ra overlay đều qua đây: nhớ lời người xem nói, đọc câu theo mẫu của theme. */
function emitEvent(ev) {
  if (ev.kind === 'chat') { voice.remember(ev.user?.id, ev.text); lastChatAt = Date.now(); }
  // lệnh chat có bốc thăm: server bốc để overlay và giọng đọc cùng một kết quả
  if (ev.kind === 'command' && typeof ev.draw === 'string') { const d = draws.pick(theme.draws, ev.draw, ev.user?.id || ''); if (d) ev.draw = d; else delete ev.draw; }
  broadcast({ type: 'event', ev });
  if (!ev.test) speak(voice.line(theme.voice, ev), { for: ev.user?.id || '', about: ev.draw ? 'draw' : ev.kind });
}
const rulesFile = (id) => path.join(DATA, `rules-${id}.json`);
const settingsFile = (id) => path.join(DATA, `theme-settings-${id}.json`);

function activate(themeId) {
  theme = loadTheme(THEME_DIRS, themeId);
  setExtraWords(theme.filter?.extraWords); // theme.json "filter.extraWords": ek yasak kelimeler
  const actionIds = theme.actions.map((a) => a.id);
  let saved = null;
  try { saved = JSON.parse(fs.readFileSync(rulesFile(theme.id), 'utf8')); } catch {}
  rules = sanitizeRules(saved || theme.rules, actionIds);
  themeSettings = settingValues(theme, readJson(settingsFile(theme.id)));
  session?.save();
  session = createSession({
    file: path.join(DATA, `session-${theme.id}.json`),
    titles: theme.titles || [],
    goals: theme.goals || [],
    playerTtlMs: (config.playerTtlMinutes || 20) * 60000,
  });
  engine = createEngine({
    getRules: () => rules,
    session,
    catalog,
    emit: (ev) => { if (ev.internal) { broadcast({ type: 'gifts', gifts: catalog.list() }, 'control'); return; } emitEvent(ev); },
    onChange: () => pushState(),
    maxJoinsPerSecond: config.maxJoinsPerSecond || 15,
  });
  console.log(`[theme] ${theme.name} (${theme.id})`);
  schedulePeriodic();
  schedulePrompts();
  setTimeout(warmDraws, 3000);
}
activate(process.env.THEME || config.theme || 'starter');

// ---------- Nội dung định kỳ (tụng kinh, lời mời, câu hỏi...) khi chat vắng ----------
function schedulePeriodic() {
  clearInterval(periodicTimer);
  const p = theme.periodic || {};
  const items = Array.isArray(p.items) ? p.items : [];
  if (!items.length) return;
  const every = Math.max(0.5, Number(p.everyMinutes) || 3) * 60000;
  periodicTimer = setInterval(() => {
    if (!themeSettings.periodicEnabled) return;
    // chỉ chạy khi phòng vắng một lúc (mặc định 20 giây không có sự kiện)
    const quiet = (Number(p.quietSeconds ?? 20) || 0) * 1000;
    if (engine.lastEventAt && Date.now() - engine.lastEventAt < quiet) return;
    firePeriodic(items[periodicIdx++ % items.length]);
  }, every);
  periodicTimer.unref?.();
}
// ---------- Lời mời tương tác khi chat vắng ----------
// theme.json "prompts": { "everySeconds": 90, "quietSeconds": 25, "items": ["Gõ xin xăm để xem quẻ...", { "text": "...", "say": "..." }] }
function schedulePrompts() {
  clearInterval(promptTimer);
  const p = theme.prompts || {};
  const items = Array.isArray(p.items) ? p.items : [];
  if (!items.length) return;
  const every = Math.max(20, Number(p.everySeconds) || 90) * 1000;
  const quiet = (Number(p.quietSeconds ?? 25) || 0) * 1000;
  lastPromptAt = Date.now();
  promptTimer = setInterval(() => {
    if (!themeSettings.periodicEnabled || Date.now() - lastPromptAt < every) return;
    if (lastChatAt && Date.now() - lastChatAt < quiet) return;
    lastPromptAt = Date.now();
    const raw = items[promptIdx++ % items.length];
    const it = typeof raw === 'string' ? { text: raw } : raw || {};
    broadcast({ type: 'event', ev: { kind: 'prompt', at: Date.now(), text: it.text || '' } });
    if (it.speak !== false) speak(it.say || it.text, { about: 'prompt' });
  }, 5000);
  promptTimer.unref?.();
}

function firePeriodic(item) {
  const it = typeof item === 'string' ? { text: item } : item || {};
  broadcast({ type: 'event', ev: { kind: 'periodic', at: Date.now(), text: it.text || '', title: it.title || theme.periodic?.title || '', action: it.action || '' } });
  if (it.speak !== false) speak(it.say || it.text, { about: 'periodic' });
}

function saveConfig(patch) {
  Object.assign(config, patch);
  Object.assign(settings, patch);
  fs.mkdirSync(DATA, { recursive: true });
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2));
}

// ---------- HTTP ----------
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif', '.svg': 'image/svg+xml', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.wav': 'audio/wav', '.mp4': 'video/mp4', '.webm': 'video/webm', '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.bin': 'application/octet-stream', '.hdr': 'application/octet-stream', '.ktx2': 'image/ktx2', '.woff2': 'font/woff2', '.ico': 'image/x-icon' };

function serveFile(res, base, rel) {
  const file = path.normalize(path.join(base, rel));
  if (!file.startsWith(base + path.sep) && file !== base) return res.writeHead(403).end();
  fs.stat(file, (err, st) => {
    if (err) return res.writeHead(404).end('Not found');
    const target = st.isDirectory() ? path.join(file, 'index.html') : file;
    fs.readFile(target, (e, buf) => {
      if (e) return res.writeHead(404).end('Not found');
      res.writeHead(200, { 'Content-Type': MIME[path.extname(target).toLowerCase()] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
      res.end(buf);
    });
  });
}

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1', ...HOSTS.filter((h) => h !== '0.0.0.0' && h !== '::')]);
const hostOk = (h) => config.allowLan || LOCAL_HOSTS.has(String(h || '').replace(/:\d+$/, '').toLowerCase());

const server = http.createServer((req, res) => {
  if (!hostOk(req.headers.host)) return res.writeHead(403).end('Forbidden host');
  const url = new URL(req.url, 'http://x');
  const p = decodeURIComponent(url.pathname);
  if (p === '/') return res.writeHead(302, { Location: '/control/' }).end();
  if (p === '/overlay' || p === '/overlay/') return res.writeHead(302, { Location: `/themes/${theme.id}/${url.search}` }).end();
  if (p === '/api/health') return json(res, { status: 'ok', app: 'tiktok-live-kit', theme: theme.id, live: manager.status.state });
  if (p === '/api/export.csv') {
    res.writeHead(200, { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': `attachment; filename="top-${theme.id}-${new Date().toISOString().slice(0, 10)}.csv"` });
    return res.end(session.csv());
  }
  if (p === '/api/theme-files') {
    // liệt kê file trong themes/<theme>/assets/<dir> (nhạc, ảnh) để theme tự nạp những gì người dùng thả vào
    const dir = String(url.searchParams.get('dir') || '').replace(/[^a-z0-9_-]/gi, '');
    let files = [];
    try { files = fs.readdirSync(path.join(theme.dir, 'assets', dir)).filter((f) => /\.(mp3|ogg|wav|m4a|png|jpe?g|webp|gif|mp4|webm|json)$/i.test(f)).sort(); } catch {}
    return json(res, { files });
  }
  if (p.startsWith('/tts/')) return serveFile(res, path.join(DATA, 'tts'), p.slice(5));
  if (p === '/vendor/lottie.min.js') return serveFile(res, path.join(ROOT, 'node_modules', 'lottie-web', 'build', 'player'), 'lottie.min.js');
  // Three.js cho theme 3D (scene.json "renderer": "3d"): /vendor/three/three.module.js, /vendor/three/addons/... (examples/jsm)
  if (p.startsWith('/vendor/three/addons/')) return serveFile(res, path.join(ROOT, 'node_modules', 'three', 'examples', 'jsm'), p.slice(21));
  if (p.startsWith('/vendor/three/')) return serveFile(res, path.join(ROOT, 'node_modules', 'three', 'build'), p.slice(14));
  if (p.startsWith('/control/')) return serveFile(res, path.join(ROOT, 'public', 'control'), p.slice(9) || 'index.html');
  if (p.startsWith('/sdk/')) return serveFile(res, path.join(ROOT, 'public', 'sdk'), p.slice(5));
  if (p.startsWith('/themes/')) {
    const [id, ...rest] = p.slice(8).split('/');
    const t = listThemes(THEME_DIRS).find((x) => x.id === id);
    return t ? serveFile(res, t.dir, rest.join('/') || 'index.html') : res.writeHead(404).end('Not found');
  }
  res.writeHead(404).end('Not found');
});
const json = (res, obj) => res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' }).end(JSON.stringify(obj));

// ---------- WebSocket ----------
const wss = new WebSocketServer({
  server, path: '/ws', maxPayload: 256 * 1024,
  verifyClient: ({ origin, req }) => {
    if (!hostOk(req.headers.host)) return false;
    if (!origin) return true; // client gốc (game Unity, script) không gửi Origin
    try { return config.allowLan || LOCAL_HOSTS.has(new URL(origin).hostname); } catch { return false; }
  },
});

const send = (ws, msg) => { if (ws.readyState === 1) ws.send(typeof msg === 'string' ? msg : JSON.stringify(msg)); };
function broadcast(msg, role) {
  const data = JSON.stringify(msg);
  for (const c of wss.clients) if (c.role && (!role || c.role === role)) send(c, data);
}

let stateTimer = null;
function stateMsg() {
  return {
    type: 'state',
    viewers: session.data.viewers,
    totals: session.data.totals,
    top: session.top(16),
    goals: session.goalsView(),
    live: manager.status,
    demo: demo.running,
    lastEventAgo: engine.lastEventAt ? Date.now() - engine.lastEventAt : null,
  };
}
function pushState() {
  if (stateTimer) return;
  stateTimer = setTimeout(() => { stateTimer = null; broadcast(stateMsg()); }, 250);
}

const publicTheme = () => ({
  id: theme.id, name: theme.name, width: theme.width, height: theme.height, actions: theme.actions, titles: theme.titles,
  text: theme.text || {}, settings: theme.settings, characters: theme.characters, animations: theme.animations, npcs: theme.npcs,
  hud: theme.hud, colors: theme.colors, sounds: theme.sounds, bigGift: theme.bigGift, reactions: theme.reactions, scene: theme.scene, goals: theme.goals,
});
// Overlay cần luật để tự sinh bảng "tặng gì được gì"; kèm tên và ảnh các quà đã gặp
const guideData = () => ({ rules, gifts: catalog.list().map((g) => ({ id: g.id, name: g.name, coins: g.coins, image: g.image })) });

function init(ws) {
  const base = { type: 'init', theme: publicTheme(), state: stateMsg(), settings: themeSettings };
  if (ws.role === 'control') send(ws, { ...base, rules, gifts: catalog.list(), presetGifts: demo.gifts.map((g) => ({ id: g.id, name: g.name, coins: g.unitCoins, image: '' })), themes: listThemes(THEME_DIRS).map(({ dir, ...t }) => t), config: { provider: config.provider || 'auto', tiktokUsername: config.tiktokUsername || '', tikfinityUrl: config.tikfinityUrl } });
  else send(ws, { ...base, players: session.active(config.snapshotPlayers || 300), guide: guideData() });
}

const demo = createDemo({ onEvent: (ev) => engine.ingest(ev, { simulated: true }) });

const CONTROL = {
  async connect(m) {
    demo.stop();
    saveConfig({ tiktokUsername: String(m.username || '').replace(/^@/, '').trim(), provider: ['auto', 'tikfinity', 'connector'].includes(m.provider) ? m.provider : 'auto' });
    manager.connect(config.tiktokUsername, config.provider);
  },
  async disconnect() { await manager.stop(); },
  sim(m) { demo.fire(m.kind, m.arg, m.arg2, m.gift); },
  crowd(m) { demo.crowd(m.n, (config.maxJoinsPerSecond || 15) * 0.8); },
  demo(m) { demo.auto(Number(m.rate) || 0, { gifts: manager.status.state === 'idle' }); pushState(); }, // đang nối live thật: giả lập không tạo quà
  test(m) {
    // Bắn thẳng một hành động của theme để xem hiệu ứng, không cộng điểm
    const a = theme.actions.find((x) => x.id === m.action);
    if (!a) return;
    const p = session.active(1)[0] || { id: 'test', name: 'Deneme', avatar: '', coins: 0, title: '', rank: 0 };
    const text = (v, max) => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : '');
    const coins = Math.max(1, Math.min(1e6, Number(m.coins) || (m.big ? 100 : 1)));
    const gift = { id: '', name: text(m.giftName, 60) || 'Deneme', image: /^https:\/\//.test(m.giftImage || '') ? text(m.giftImage, 500) : '', coins };
    const ev = { kind: 'gift', at: Date.now(), user: { ...p, isPlayer: true }, gift, count: 1, total: coins, action: a.id, label: text(m.label, 60) || a.label, big: Boolean(m.big), test: true };
    broadcast({ type: 'event', ev });
    speak(voice.line(theme.voice, { ...ev, test: false }), { for: p.id });
  },
  reset() { session.reset(); engine.reset(); broadcast({ type: 'reset' }); pushState(); },
  saveRules(m) {
    rules = sanitizeRules(m.rules, theme.actions.map((a) => a.id));
    fs.mkdirSync(DATA, { recursive: true });
    fs.writeFileSync(rulesFile(theme.id), JSON.stringify(rules, null, 2));
    broadcast({ type: 'rules', rules }, 'control');
    broadcast({ type: 'guide', ...guideData() }, 'overlay');
  },
  saveSettings(m) {
    themeSettings = settingValues(theme, { ...themeSettings, ...(m.values || {}) });
    fs.mkdirSync(DATA, { recursive: true });
    fs.writeFileSync(settingsFile(theme.id), JSON.stringify(themeSettings, null, 2));
    broadcast({ type: 'settings', values: themeSettings });
  },
  testVoice(m) { const was = themeSettings.voiceEnabled; themeSettings.voiceEnabled = true; speak(String(m.text || 'Merhaba, bu bir ses denemesidir').slice(0, 200)); themeSettings.voiceEnabled = was; },
  periodicNow() { const items = theme.periodic?.items || []; if (items.length) firePeriodic(items[periodicIdx++ % items.length]); },
  resetRules() { try { fs.unlinkSync(rulesFile(theme.id)); } catch {} rules = sanitizeRules(theme.rules, theme.actions.map((a) => a.id)); broadcast({ type: 'rules', rules }, 'control'); },
  setTheme(m) {
    if (!listThemes(THEME_DIRS).some((t) => t.id === m.id)) return;
    saveConfig({ theme: m.id });
    activate(m.id);
    broadcast({ type: 'reload' }, 'overlay');
    for (const c of wss.clients) if (c.role === 'control') init(c);
  },
};

wss.on('connection', (ws) => {
  ws.role = null;
  ws.alive = true;
  ws.budget = { at: Date.now(), n: 0 };
  ws.on('pong', () => { ws.alive = true; });
  ws.on('message', async (raw, isBinary) => {
    if (isBinary) return ws.close(1003, 'text only');
    const now = Date.now();
    if (now - ws.budget.at > 5000) ws.budget = { at: now, n: 0 };
    if (++ws.budget.n > 120) return ws.close(1008, 'rate limit');
    let m;
    try { m = JSON.parse(raw); } catch { return; }
    if (!m || typeof m.type !== 'string') return;
    if (m.type === 'hello') {
      if (!['control', 'overlay'].includes(m.role)) return send(ws, { type: 'error', message: 'geçersiz rol' });
      ws.role = m.role;
      return init(ws);
    }
    if (m.type === 'ping') return send(ws, { type: 'pong', t: m.t });
    if (ws.role !== 'control') return send(ws, { type: 'error', message: 'Komut yalnızca kontrol paneli içindir' });
    const fn = CONTROL[m.type];
    if (!fn) return;
    try { await fn(m); } catch (err) { console.error('[control]', m.type, err); send(ws, { type: 'error', message: String(err.message || err) }); }
  });
});

const heartbeat = setInterval(() => {
  for (const c of wss.clients) { if (!c.alive) { c.terminate(); continue; } c.alive = false; c.ping(); }
  if (manager.status.state === 'connected') pushState(); // cập nhật "sự kiện cuối cách đây"
}, 15000);

// ---------- Kết nối live ----------
const manager = createManager({
  config,
  onEvent: (ev) => engine.ingest(ev),
  onStatus: (st) => {
    // nối được buổi live thật thì tắt giả lập: từ đây chỉ còn người xem thật
    if (st?.state === 'connected' && demo.running) { demo.stop(); console.log('[live] bağlandı, demo kapatıldı'); }
    pushState();
  },
  lastEventAt: () => engine.lastEventAt,
});

for (const h of HOSTS.slice(1)) { // địa chỉ thêm: cùng xử lý, cùng WebSocket
  const extra = http.createServer(server.listeners('request')[0]);
  extra.on('upgrade', (req, socket, head) => server.emit('upgrade', req, socket, head));
  extra.on('error', (e) => console.warn(`[ağ] dinlenemiyor ${h}:${PORT} (${e.code || e.message})`));
  extra.listen(PORT, h, () => console.log(`  - Ek adres: http://${h}:${PORT}/overlay`));
}

server.listen(PORT, HOSTS[0], () => {
  console.log(`\n  TikTok Live Kit · theme: ${theme.name}`);
  console.log(`  - Kontrol paneli: http://localhost:${PORT}/`);
  console.log(`  - Overlay (OBS Browser source, ${theme.width}x${theme.height}): http://localhost:${PORT}/overlay\n`);
  if (config.autoConnect && (config.tiktokUsername || config.provider === 'tikfinity')) manager.connect(config.tiktokUsername, config.provider);
});

async function shutdown() {
  clearInterval(heartbeat);
  clearInterval(periodicTimer);
  demo.stop();
  session.save();
  await manager.stop();
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
process.on('uncaughtException', (err) => console.error('[yakalanmamış hata]', err));
process.on('unhandledRejection', (err) => console.error('[promise hatası]', err));
