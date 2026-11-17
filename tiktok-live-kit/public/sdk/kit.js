// Kit: khởi động overlay của theme, nối sự kiện live với cảnh, chạy hành động khai báo trong theme.json.
//
// index.html của theme chỉ cần:
//   <div id="stage"></div>
//   <script src="/sdk/live-sdk.js"></script> ... <script src="/sdk/kit.js"></script>
//   <script src="theme.js"></script>   (tuỳ chọn: hành động / vẽ riêng)
//
// Hành động (theme.json "actions"[].steps, "bigGift", "reactions") là danh sách bước chạy lần lượt trên người tặng:
//   { "walk": "offer" }                 đi tới điểm (scene.json points) / "home" (về chỗ) / "seat"
//   { "pose": "stand" }                 đổi tư thế
//   { "play": "bow", "times": 3, "each": [ ...bước tức thì... ] }   chạy hoạt cảnh n lần ("times": "count" = theo số quà)
//   { "wait": 800 }
//   { "fx": "emit", "preset": "smoke", "at": "censerMouth", "count": 8 }   hiệu ứng (xem Kit.fx)
//   { "fx": "rain" | "halo" | "rays" | "pillar" | "text" | "fly" | "sprite" | "fireworks" | "flash" | "shake", ... }
//   { "spotlight": true }  { "camera": "person", "zoom": 1.6 }  { "sound": "chuong" }  { "aura": 1 }  { "boost": 1.3 }
//   { "fx3d": "fireworks" | "confetti" | "beam" | "ring" }   hiệu ứng 3D (cảnh 2D tự đổi sang hiệu ứng 2D tương ứng)
//   { "stage": "party", "duration": 6000 } | { "stage": "calm" } | { "stage": "strobe" }   sân khấu 3D: đèn quét, laser (cảnh 2D bỏ qua)
//   { "say": "Cảm ơn {ten}!" }          bong bóng chữ trên đầu
//   { "crowd": [ ...bước... ] }         cả đám đông cùng làm
//   { "npc": "su-tru-tri", "steps": [ ...bước... ] }
//   { "js": "tenHam" }                  gọi hàm riêng: Kit.action('tenHam', (person, ev, ctx) => { ... })
// Chữ trong bước được điền {ten} {qua} {count} {total} {label}.

(function () {
  const K = window.Kit;
  const handlers = {};
  const custom = {};
  K.events = {
    on(name, fn) { (handlers[name] ||= []).push(fn); return K.events; },
    emit(name, ...args) { for (const fn of handlers[name] || []) try { fn(...args); } catch (e) { console.error(`[Kit] lỗi trong "${name}"`, e); } },
  };
  K.on = K.events.on;
  K.action = (name, fn) => { custom[name] = fn; };

  let theme = null, settings = {}, started = false;
  const fill = (s, ev = {}) => String(s).replace(/\{(\w+)\}/g, (_, k) => ({ ten: ev.user?.name, qua: ev.gift?.name || ev.label, count: ev.count, total: ev.total, label: ev.label, likes: ev.count }[k] ?? ''));

  // ---------- Bộ chạy bước ----------
  function where(at, person) {
    if (!at || at === 'person' || at === 'feet') return person ? { x: person.x, y: person.y } : { x: K.W / 2, y: K.H / 2 };
    if (at === 'head') return person ? K.scene.P.head(person) : { x: K.W / 2, y: K.H / 2 };
    if (at === 'center') return { x: K.W / 2, y: K.H / 2 };
    return K.scene.point(at) || { x: K.W / 2, y: K.H / 2 };
  }

  const num = (v, ev, max = 10) => (v === 'count' ? Math.min(max, Math.max(1, ev?.count || 1)) : v === 'likes' ? Math.min(max, Math.max(1, Math.ceil((ev?.count || 1) / 3))) : Number(v) || 1);

  // Bước tức thì (không chiếm thời gian của nhân vật)
  function instant(step, person, ev) {
    const P = K.scene.P;
    if (step.fx) {
      const at = where(step.at, person);
      switch (step.fx) {
        case 'emit': K.fx.emit(step.preset || 'spark', { ...step, x: at.x + (step.dx || 0), y: at.y + (step.dy || 0), count: num(step.count ?? 10, ev, 200) }); break;
        case 'rain': K.fx.rain(step.preset || 'petal', { ...step, count: num(step.count ?? 40, ev, 300) }); break;
        case 'halo': K.fx.halo(at.x, at.y, step); break;
        case 'rays': K.fx.rays({ ...step, x: at.x, y: at.y }); break;
        case 'pillar': K.fx.pillar(at.x, at.y, { height: person ? K.scene.height(person) * 6 : 600, ...step }); break;
        case 'text': K.fx.text(at.x, at.y - 10, fill(step.text || '+{total}', ev), step); break;
        case 'fly': K.fx.fly(step.what || 'lotus', where(step.from || 'head', person), where(step.to, person), { ...step, count: num(step.count ?? 3, ev, 20) }); break;
        case 'sprite': K.fx.sprite(step.image, { ...step, x: at.x + (step.dx || 0), y: at.y + (step.dy || 0) }); break;
        case 'fireworks': K.fx.fireworks(step); break;
        case 'flash': K.fx.flash(step); break;
        case 'shake': K.fx.shake(step); break;
      }
    } else if (step.fx3d) {
      if (K.scene.fx3d) K.scene.fx3d(step, person, ev);
      else fx3dIn2D(step, person, ev);
    } else if (step.stage) K.scene.stage?.(step)
    else if (step.spotlight && person) K.fx.spotlight(() => K.scene.P.head(person), { color: step.color, duration: step.duration ?? 4000 });
    else if (step.camera) K.scene.focus(step.camera === 'person' ? person : where(step.camera, person), step);
    else if (step.sound) K.audio.sfx(step.sound, step);
    else if (step.aura && person) P.aura(person, Number(step.aura) || 1);
    else if (step.boost && person) P.boost(person, Number(step.boost) || 1.25, step.duration ?? 4000);
    else if (step.say && person) P.say(person, fill(step.say, ev), step.duration);
    else if (step.toast) K.hud.toast(fill(step.toast, ev));
    else if (step.crowd) for (const q of [...K.scene.people(), ...(K.scene.extras?.() || [])]) { if (q.task || q.tasks.length) continue; K.scene.P.wait(q, Math.random() * (step.stagger ?? 400)); run(step.crowd, q, ev); }
    else if (step.npc) { const n = K.scene.npc(step.npc); if (n) run(step.steps || [], n, ev); }
    else if (step.js) { const fn = custom[step.js]; if (fn) fn(person, ev, { theme, settings }); else console.warn(`[Kit] chưa có Kit.action('${step.js}')`); }
  }

  // Cảnh 2D gặp bước fx3d: dùng hiệu ứng 2D gần nhất để một theme chạy được cả hai kiểu
  function fx3dIn2D(step, person, ev) {
    const at = where(step.at || (person ? 'head' : 'center'), person);
    if (step.fx3d === 'fireworks') K.fx.fireworks({ bursts: step.bursts ?? 4 });
    else if (step.fx3d === 'confetti') K.fx.rain('confetti', { count: num(step.count ?? 120, ev, 300) });
    else if (step.fx3d === 'beam') K.fx.pillar(at.x, person ? person.y : at.y, { height: person ? K.scene.height(person) * 6 : 600 });
    else if (step.fx3d === 'ring') K.fx.halo(at.x, person ? person.y - K.scene.height(person) * 0.5 : at.y, {});
  }

  /** Chạy danh sách bước trên một người (hoặc không có người: chạy lần lượt theo thời gian). */
  function run(steps, person, ev) {
    if (!Array.isArray(steps)) return;
    const P = K.scene.P;
    if (!person) {
      let delay = 0;
      for (const s of steps) {
        if (s.wait) { delay += s.wait; continue; }
        if (s.walk || s.pose || s.play) continue;
        setTimeout(() => instant(s, null, ev), delay);
      }
      return;
    }
    for (const s of steps) {
      if (s.walk) P.walkTo(person, s.walk);
      else if (s.pose) P.pose(person, s.pose);
      else if (s.play) P.play(person, s.play, num(s.times ?? 1, ev, s.max ?? 6), s.each ? (p) => s.each.forEach((e) => instant(e, p, ev)) : null);
      else if (s.wait) P.wait(person, s.wait);
      else P.do(person, (p) => instant(s, p, ev));
    }
  }
  K.run = run;

  const DEFAULT_STEPS = [{ aura: 1 }, { fx: 'emit', preset: 'spark', at: 'head', count: 12 }, { play: 'nod' }];
  const DEFAULT_BIG = [{ camera: 'person', zoom: 1.6, duration: 3500 }, { spotlight: true }, { fx: 'flash', strength: 0.35 }, { boost: 1.3, duration: 4000 }];
  const DEFAULT_REACTIONS = {
    like: [{ fx: 'emit', preset: 'heart', at: 'head', count: 'likes' }],
    follow: [{ say: '➕ Takip etti' }, { fx: 'emit', preset: 'spark', at: 'head', count: 12 }],
    share: [{ say: '🔗 Paylaştı' }, { fx: 'emit', preset: 'spark', at: 'head', count: 12 }],
    title: [{ aura: 1 }, { fx: 'emit', preset: 'star', at: 'head', count: 16 }, { toast: '{ten} yeni unvana ulaştı' }],
    goal: [{ fx: 'rays', at: 'focus' }, { fx: 'rain', preset: 'confetti', count: 80 }],
  };
  const reaction = (name) => theme.reactions?.[name] ?? DEFAULT_REACTIONS[name] ?? [];

  // ---------- Sự kiện live ----------
  function onEvent(kind, ev) {
    const S = K.scene;
    switch (kind) {
      case 'join': S.ensure(ev.user); run(reaction('join'), S.person(ev.user.id), ev); break;
      case 'chat': {
        K.hud.remember(ev.user.id, ev.text);
        if (!ev.user.isPlayer) break;
        const p = S.ensure(ev.user);
        if (!p) break;
        p.lastActive = performance.now();
        if (!S.skinFromChat(ev.user, ev.text)) S.P.say(p, ev.text);
        if (!ev.command && !p.task && !p.tasks.length) run(reaction('chat'), p, ev); // theme.json reactions.chat: người chat làm động tác
        break;
      }
      case 'like': { const p = ev.user.isPlayer && S.ensure(ev.user); if (p) run(reaction('like'), p, ev); if (theme.sounds?.like !== false) K.audio.sfx('like'); break; }
      case 'gift': {
        const p = S.ensure(ev.user);
        if (p) p.lastActive = performance.now();
        const action = (theme.actions || []).find((a) => a.id === ev.action);
        run(action?.steps || DEFAULT_STEPS, p, ev);
        if (ev.big) run(theme.bigGift?.steps || DEFAULT_BIG, p, ev);
        for (const n of theme.npcs || []) { const r = n.reactions?.[ev.big ? 'bigGift' : 'gift']; if (r) run(r, S.npc(n.id), ev); }
        K.hud.giftCard(ev);
        K.hud.ticker(ev);
        break;
      }
      case 'command': {
        const p = S.ensure(ev.user); const a = (theme.actions || []).find((x) => x.id === ev.action);
        if (p && a) run(a.steps || DEFAULT_STEPS, p, ev);
        if (ev.draw) K.hud.draw?.(ev); // lá thăm server vừa bốc (theme.json "draws")
        break;
      }
      case 'follow': case 'share': case 'title': { const p = S.ensure(ev.user); run(reaction(kind), p, ev); break; }
      case 'goal': run(reaction('goal'), null, ev); K.hud.toast(`${ev.label}: ${Number(ev.value).toLocaleString('tr-TR')}`); break;
      case 'periodic': {
        K.hud.periodic(ev);
        const a = ev.action && (theme.actions || []).find((x) => x.id === ev.action);
        if (a) run(a.steps, null, ev);
        for (const n of theme.npcs || []) if (n.reactions?.periodic) run(n.reactions.periodic, S.npc(n.id), ev);
        break;
      }
      case 'prompt': K.hud.toast(ev.text, 6000); break;
      case 'tts': if (!Live.muted) K.audio.voice(ev.url, () => K.events.emit('speak', ev), () => K.events.emit('speakEnd', ev)); break;
    }
    K.events.emit(kind, ev);
  }

  // ---------- Vùng an toàn khi live TikTok (khung 1080 x 1920) ----------
  // Số đo ước lượng trên điện thoại, TikTok không công bố chính thức. Mở overlay với ?safe để thấy các vùng bị che.
  //   top      tên kênh, số người xem, hàng người tặng quà
  //   side     máy màn hình dài (20:9) phóng khung cho đầy chiều cao nên cắt mất hai bên
  //   chatTop  từ đây xuống là khung bình luận (nửa trái, rộng tới chatRight)
  //   bottom   từ đây xuống là ô nhập bình luận, nút quà, nút chia sẻ
  //   hearts   dải bên phải tim bay lên (từ heartsTop tới bottom)
  K.safe = { top: 240, side: 100, chatTop: 1250, chatRight: 720, bottom: 1760, heartsLeft: 950, heartsTop: 1300 };

  function showSafeZones(stage) {
    const z = K.safe, sx = K.W / 1080, sy = K.H / 1920;
    const box = (x, y, w, h, label) => `<div style="position:absolute;left:${x * sx}px;top:${y * sy}px;width:${w * sx}px;height:${h * sy}px;background:rgba(255,40,40,.28);outline:2px dashed rgba(255,90,90,.9);color:#fff;font:700 22px system-ui;display:flex;align-items:center;justify-content:center;text-align:center;text-shadow:0 1px 3px #000">${label}</div>`;
    const el = document.createElement('div');
    el.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:99';
    el.innerHTML = [
      box(0, 0, 1080, z.top, 'Kanal adı · izleyici · en çok gönderenler'),
      box(0, z.top, z.side, z.chatTop - z.top, 'Kesilen alan'),
      box(1080 - z.side, z.top, z.side, z.heartsTop - z.top, 'Kesilen alan'),
      box(0, z.chatTop, z.chatRight, z.bottom - z.chatTop, 'Yorum alanı'),
      box(z.heartsLeft, z.heartsTop, 1080 - z.heartsLeft, z.bottom - z.heartsTop, 'Tim bay'),
      box(0, z.bottom, 1080, 1920 - z.bottom, 'Yorum kutusu · hediye düğmesi'),
    ].join('');
    stage.appendChild(el);
  }

  // ---------- Khởi động ----------
  function start({ theme: t, players, state, guide }) {
    theme = t;
    settings = Live.settings || {};
    if (!started) {
      started = true;
      const stage = document.getElementById('stage') || document.body.appendChild(Object.assign(document.createElement('div'), { id: 'stage' }));
      stage.style.overflow = 'hidden';
      const canvas = document.createElement('canvas');
      canvas.width = K.W; canvas.height = K.H;
      canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%';
      stage.prepend(canvas);
      Live.stage(stage, K.W, K.H);
      // scene.json "renderer": "3d": dùng cảnh Three.js (sdk/scene3d.js), cùng giao diện với cảnh 2D
      if (theme.scene?.renderer === '3d') {
        if (K.scene3d) K.scene = K.scene3d;
        else console.error('[Kit] scene.json "renderer": "3d" cần nạp /sdk/scene3d.js trong index.html (xem themes/template-3d)');
      }
      K.scene.init({ canvas, theme, settings });
      K.hud.init({ stage, theme });
      if (new URLSearchParams(location.search).has('safe')) showSafeZones(stage);
      if (theme.scene?.bpm) K.fx.beat.bpm = theme.scene.bpm;
      loop();
      K.events.emit('start', theme);
    }
    K.audio.configure(settings, theme.sounds);
    K.hud.guide(guide, theme.characters);
    // dựng lại đám đông đang có (OBS tải lại trang, mất mạng chốc lát...)
    for (const p of (players || []).slice().reverse()) if (p.isPlayer !== false) K.scene.ensure(p, { instant: true });
    applyState(state);
  }

  function applyState(s) {
    if (!s) return;
    K.scene.seatTop(s.top);
    K.hud.state(s, K.scene.people().length);
  }

  let last = performance.now();
  // scene.json "fps": giới hạn số hình vẽ mỗi giây (vd 30) để dành máy cho phần mềm phát live; mặc định theo màn hình
  function loop(t = performance.now()) {
    requestAnimationFrame(loop);
    const cap = theme?.scene?.fps;
    if (cap && t - last < 1000 / cap - 2) return;
    const dt = Math.min(50, t - last); last = t;
    K.scene.frame(t, dt);
    K.events.emit('frame', t, dt);
  }

  Live.on('ready', start);
  Live.on('state', applyState);
  Live.on('settings', (v) => { settings = v; K.scene.configure(v); K.audio.configure(v, theme?.sounds); });
  Live.on('reset', () => { K.scene.reset(); K.hud.reset(); });
  Live.on('guide', (g) => K.hud.guide(g, theme?.characters));
  for (const k of ['join', 'chat', 'like', 'gift', 'command', 'follow', 'share', 'title', 'goal', 'periodic', 'prompt', 'tts']) Live.on(k, (ev) => theme && onEvent(k, ev));

  // Mở trang đúng lúc server đang khởi động lại có thể kẹt ở màn trống: chưa dựng được cảnh thì tự tải lại
  setTimeout(function watchdog() {
    if (started && document.querySelector('#stage canvas')) return;
    console.warn('[Kit] chưa dựng được cảnh, tải lại trang');
    location.reload();
  }, 12000);
})();
