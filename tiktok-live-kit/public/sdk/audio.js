// Kit.audio: nhạc nền, tiếng hiệu ứng, giọng đọc. Chỉ dùng file thật của theme:
//   assets/music/*.mp3   phát lặp theo danh sách
//   assets/sfx/<ten>.mp3 Kit.audio.sfx('<ten>'), mỗi tên có thời gian nghỉ để live đông không dồn dập
//   giọng đọc            server gửi url, phát lần lượt, nhạc tự nhỏ khi đang đọc
// Cấu hình nghỉ theo tên trong theme.json: "sounds": { "chuong": { "cooldown": 3000, "volume": 0.8 } }

(function () {
  let ctx = null, master, musicBus, sfxBus, voiceBus, duck;
  const buffers = new Map();   // tên -> AudioBuffer
  const lastAt = new Map();
  let recent = [];
  let sfxList = [];
  const vol = { music: 0.3, sfx: 0.6, voice: 0.9 };
  let soundsCfg = {};

  function init() {
    if (ctx) return ctx;
    ctx = Live.audio();
    if (!ctx) return null;
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18; comp.ratio.value = 4; comp.attack.value = 0.01; comp.release.value = 0.4;
    comp.connect(ctx.destination);
    master = ctx.createGain(); master.connect(comp);
    duck = ctx.createGain(); duck.connect(master);
    musicBus = ctx.createGain(); musicBus.connect(duck);
    sfxBus = ctx.createGain(); sfxBus.connect(master);
    voiceBus = ctx.createGain(); voiceBus.connect(master);
    apply();
    loadSfx();
    startMusic();
    return ctx;
  }

  function apply() {
    if (!ctx) return;
    musicBus.gain.setTargetAtTime(vol.music, ctx.currentTime, 0.4);
    sfxBus.gain.setTargetAtTime(vol.sfx, ctx.currentTime, 0.1);
    voiceBus.gain.setTargetAtTime(vol.voice * 1.3, ctx.currentTime, 0.1);
  }

  function duckMusic(level, seconds) {
    if (!ctx) return;
    const t = ctx.currentTime;
    duck.gain.cancelScheduledValues(t);
    duck.gain.setTargetAtTime(level, t, 0.15);
    if (seconds) duck.gain.setTargetAtTime(1, t + seconds, 1);
  }

  const listDir = async (dir) => { try { return (await (await fetch(`/api/theme-files?dir=${dir}`)).json()).files || []; } catch { return []; } };

  async function loadSfx() {
    sfxList = (await listDir('sfx')).filter((f) => /\.(mp3|ogg|wav|m4a)$/i.test(f));
    for (const f of sfxList) {
      try { buffers.set(f.replace(/\.[^.]+$/, '').toLowerCase(), await ctx.decodeAudioData(await (await fetch('assets/sfx/' + encodeURIComponent(f))).arrayBuffer())); }
      catch (e) { console.warn('[Kit.audio] không đọc được', f, e); }
    }
  }

  /** Phát tiếng hiệu ứng theo tên file (không đuôi). Không có file thì im lặng. */
  function sfx(name, o = {}) {
    if (!name || !init()) return false;
    const key = String(name).toLowerCase();
    const buf = buffers.get(key);
    if (!buf) return false;
    const cfg = soundsCfg[key] || {};
    const now = performance.now();
    const cooldown = o.cooldown ?? cfg.cooldown ?? 400;
    if (now - (lastAt.get(key) || -1e9) < cooldown) return false;
    recent = recent.filter((t) => now - t < 1500);
    if (recent.length >= (cfg.priority ? 6 : 4)) return false; // đông tiếng thì bỏ bớt
    lastAt.set(key, now); recent.push(now);
    const src = ctx.createBufferSource(), g = ctx.createGain();
    src.buffer = buf;
    src.playbackRate.value = (o.rate ?? 1) * (cfg.vary ? 1 + (Math.random() - 0.5) * cfg.vary : 1);
    g.gain.value = (o.volume ?? 1) * (cfg.volume ?? 1);
    src.connect(g); g.connect(sfxBus);
    src.start(Math.ceil(ctx.currentTime / 0.1) * 0.1); // vào lưới 100ms cho đều
    if (cfg.duck) duckMusic(cfg.duck, Math.min(6, buf.duration));
    return true;
  }

  // ---------- Nhạc nền ----------
  let musicEl = null, playlist = [], idx = 0;
  async function startMusic() {
    playlist = (await listDir('music')).filter((f) => /\.(mp3|ogg|wav|m4a)$/i.test(f));
    if (!playlist.length) return;
    musicEl = new Audio();
    musicEl.onended = () => { idx = (idx + 1) % playlist.length; playTrack(); };
    ctx.createMediaElementSource(musicEl).connect(musicBus);
    playTrack();
  }
  function playTrack() { musicEl.src = 'assets/music/' + encodeURIComponent(playlist[idx]); musicEl.play().catch(() => {}); }

  // ---------- Giọng đọc ----------
  const voiceQ = [];
  let speaking = false;
  function voice(url, onStart, onEnd) {
    if (!init()) return;
    if (voiceQ.length > 10) voiceQ.shift()?.onEnd?.();
    voiceQ.push({ url, onStart, onEnd });
    nextVoice();
  }
  function nextVoice() {
    if (speaking || !voiceQ.length) return;
    speaking = true;
    const { url, onStart, onEnd } = voiceQ.shift();
    const el = new Audio(url);
    el.crossOrigin = 'anonymous';
    ctx.createMediaElementSource(el).connect(voiceBus);
    el.onplay = () => { duckMusic(0.25); onStart?.(); };
    let done = false;
    const finish = () => { if (done) return; done = true; duckMusic(1); speaking = false; onEnd?.(); setTimeout(nextVoice, 300); };
    el.onended = el.onerror = finish;
    el.play().catch(finish);
  }

  function configure(settings = {}, sounds = {}) {
    vol.music = (settings.musicVolume ?? 30) / 100;
    vol.sfx = (settings.sfxVolume ?? 60) / 100;
    vol.voice = (settings.voiceVolume ?? 90) / 100;
    soundsCfg = Object.fromEntries(Object.entries(sounds || {}).map(([k, v]) => [k.toLowerCase(), v]));
    if (init()) apply();
  }

  window.Kit = window.Kit || {};
  window.Kit.audio = { init, sfx, voice, configure, duckMusic, has: (n) => buffers.has(String(n).toLowerCase()), get list() { return sfxList; } };
})();
