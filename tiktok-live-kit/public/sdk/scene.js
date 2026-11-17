// Kit.scene: engine "đám đông trong một không gian". Nền ảnh/video, người xem thành nhân vật đứng/ngồi
// theo phối cảnh của scene.json, ghế danh dự cho top, NPC dựng sẵn, camera zoom, nhãn tên, bong bóng chat.
//
// Nhân vật khai báo trong theme.json "characters": mỗi mẫu người là một tờ khung hình (png chia đều ngang)
// hoặc ảnh động (gif / webm). Chưa có ảnh thì engine vẽ hình người giữ chỗ.
//   { "id": "ba", "label": "Bà", "keywords": ["bà"], "sheet": "assets/chars/ba.png", "frames": 5,
//     "poses": { "idle": 0, "bowHalf": 1, "bowFull": 2, "stand": 3, "offer": 4 }, "walk": [3], "weight": 1 }
//   Khung đi theo hướng (tuỳ chọn): "walkUp": [...] đi lên/vào (thấy lưng), "walkDown": [...] đi xuống/ra (thấy mặt),
//   "walkSide": [...] đi ngang (vẽ nhân vật quay sang phải, engine tự lật khi đi sang trái). Thiếu hướng nào thì dùng "walk".
// Hoạt cảnh khai báo trong theme.json "animations": { "bow": { "frames": ["idle","bowHalf","bowFull","bowHalf"], "ms": 1300 } }
// scene.json "fill": { "rows": 2 }: luôn lấp kín N hàng đầu bằng người không tên (không tính vào số người xem);
// các hàng đó cố định, người xem thật ngồi từ hàng phía sau.

(function () {
  const K = window.Kit;
  const G = K.geometry;
  const W = 1080, H = 1920;
  K.W = W; K.H = H;

  let S = G.normalize({});
  let theme = { characters: [], animations: {}, npcs: [], colors: {} };
  let canvas = null, ctx = null;
  const persons = new Map();
  const npcs = new Map();
  let layout = { density: 0, slots: [] };
  let seats = [];
  let chars = [];
  let anims = {};
  let bgImage = null, bgVideo = null;
  const cam = { x: W / 2, y: H / 2, z: 1, tx: W / 2, ty: H / 2, tz: 1, queue: [], until: 0 };
  let maxTags = 8;
  let settings = {};

  const DEFAULT_ANIMS = {
    bow: { frames: ['idle', 'bowHalf', 'bowFull', 'bowFull', 'bowHalf'], ms: 1300 },
    offer: { frames: ['stand', 'offer', 'offer', 'stand'], ms: 1100 },
    nod: { frames: ['idle', 'bowHalf', 'idle'], ms: 700 },
    cheer: { frames: ['stand', 'cheer', 'stand', 'cheer'], ms: 900 },
    dance: { frames: ['dance1', 'dance2'], ms: 520 },
  };

  const now = () => performance.now();
  const rand = (a, b) => a + Math.random() * (b - a);
  const hash = (s) => { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
  const col = (k, d) => theme.colors?.[k] || d;

  // ---------- Khởi tạo ----------
  function init(opts) {
    canvas = opts.canvas; ctx = canvas.getContext('2d');
    theme = opts.theme || theme;
    settings = opts.settings || {};
    S = G.normalize(theme.scene || {});
    maxTags = theme.scene?.maxTags ?? 8;
    anims = { ...DEFAULT_ANIMS, ...(theme.animations || {}) };
    seats = S.seats.map((p) => ({ ...p, taken: null, vip: true }));
    chars = (theme.characters || []).map((c) => ({
      ...c,
      sheetD: c.sheet ? K.assets.sheet(c.sheet, c.frames || 1) : null,
      animD: c.idleAnim ? K.assets.get(c.idleAnim) : null,
    }));
    if (!chars.length) chars = [{ id: 'default', label: 'Người', placeholder: true }];
    const sc = theme.scene || {};
    bgImage = sc.background ? K.assets.get(sc.background) : null;
    bgVideo = sc.backgroundVideo ? K.assets.get(sc.backgroundVideo) : null;
    relayout(true);
    for (const n of theme.npcs || []) addNpc(n);
    setAmbient(settings.ambientFx !== false);
  }

  function configure(s) { settings = s || {}; setAmbient(settings.ambientFx !== false); }

  let ambientOn = null;
  function setAmbient(on) {
    if (on === ambientOn) return;
    ambientOn = on;
    const list = theme.scene?.emitters || [];
    list.forEach((e, i) => {
      const id = 'scene-emitter-' + i;
      if (!on && !e.always) { K.fx.stop(id); return; }
      const at = point(e.at) || { x: e.x ?? W / 2, y: e.y ?? H / 2 };
      K.fx.emitter(id, e.preset || 'smoke', { ...e, x: at.x, y: at.y });
    });
  }

  /** Điểm đặt tên trong scene.json "points" (ví dụ "censerMouth": [540, 940]). */
  function point(name) {
    if (!name) return null;
    if (typeof name === 'object') return Array.isArray(name) ? { x: name[0], y: name[1] } : name; // [x, y] hoặc { x, y }
    const p = theme.scene?.points?.[name];
    return p ? (Array.isArray(p) ? { x: p[0], y: p[1] } : p) : null;
  }

  // ---------- Người lấp chỗ: giữ kín N hàng đầu ----------
  const fillers = new Map();
  let fillSeq = 0, fillAt = 0;
  function frontSlots() {
    const rows = theme.scene?.fill?.rows || 0;
    if (!rows) return [];
    const ys = [...new Set(layout.slots.map((s) => s.y))].sort((a, b) => a - b).slice(0, rows);
    return layout.slots.filter((s) => ys.includes(s.y));
  }
  function maintainFill(t) {
    if (t - fillAt < 800) return;
    fillAt = t;
    const front = new Set(frontSlots());
    for (const [id, f] of fillers) {
      if (front.has(f.slot) && f.slot.taken === id) continue;
      if (f.slot.taken === id) f.slot.taken = null;
      fillers.delete(id);
    }
    for (const s of front) {
      if (s.taken) continue;
      const id = 'fill:' + fillSeq++;
      const f = makePerson({ id, name: '' }, { npc: true, filler: true, showName: false, x: s.x, y: s.y, pose: 'idle', homePose: 'idle' });
      f.slot = s; s.taken = id;
      fillers.set(id, f);
    }
  }

  // ---------- Chỗ đứng: tự giãn theo số người ----------
  let lastRelayout = 0;
  function relayout(force = false) {
    const count = [...persons.values()].filter((p) => !p.leaving && !p.slot?.vip).length;
    const t = now();
    if (!force && t - lastRelayout < 2000) return;
    lastRelayout = t;
    const next = G.layoutFor(S, count + 4);
    if (!force && next.density === layout.density) return;
    // phòng thưa ra chỉ khi vắng hẳn (tránh nhảy qua nhảy lại)
    if (!force && next.density > layout.density && count > layout.slots.length * 0.45) return;
    const movers = [...persons.values()].filter((p) => !p.leaving && !p.slot?.vip).sort((a, b) => a.joinedAt - b.joinedAt);
    layout = { density: next.density, slots: next.slots.map((s) => ({ ...s, taken: null })) };
    fillers.clear(); fillAt = 0;
    const front = new Set(frontSlots());
    const open = layout.slots.filter((s) => !front.has(s));
    movers.forEach((p, i) => {
      const s = open[i];
      if (!s) { leave(p); return; }
      p.slot = s; s.taken = p.id;
      if (!p.tasks.length && !p.task) p.tasks.push({ type: 'walk', pts: [{ x: s.x, y: s.y }] });
    });
  }

  function freeSlot() {
    const front = new Set(frontSlots());
    let s = layout.slots.find((x) => !x.taken && !front.has(x));
    if (s) return s;
    let oldest = null;
    for (const p of persons.values()) if (!p.leaving && !p.slot?.vip && !p.tasks.length && !p.task && (!oldest || p.lastActive < oldest.lastActive)) oldest = p;
    if (!oldest) return null;
    s = oldest.slot;
    leave(oldest);
    return s;
  }

  // ---------- Người ----------
  function pickChar(id, preferred) {
    if (preferred) { const c = chars.find((x) => x.id === preferred); if (c) return c; }
    const total = chars.reduce((a, c) => a + (c.weight ?? 1), 0);
    let r = (hash(id) % 1000) / 1000 * total;
    for (const c of chars) { r -= c.weight ?? 1; if (r <= 0) return c; }
    return chars[0];
  }

  function makePerson(user, extra = {}) {
    return {
      id: user.id, name: user.name || 'Misafir', avatar: user.avatar ? Live.img(user.avatar) : null,
      char: pickChar(user.id, user.character), flip: hash(user.id + 'f') % 2 === 1, tint: (hash(user.id + 't') % 17) - 8,
      x: W / 2, y: H + 80, pose: 'idle', anim: null, tasks: [], task: null, bubble: null, aura: 0, boost: 1, boostUntil: 0,
      lastActive: now() - 15000, joinedAt: now(), rank: user.rank || 0, title: user.title || '', coins: user.coins || 0, ...extra,
    };
  }

  function ensure(user, { instant = false } = {}) {
    if (!user?.id) return null;
    let p = persons.get(user.id);
    if (p) {
      p.name = user.name || p.name;
      if (user.rank !== undefined) p.rank = user.rank;
      if (user.title) p.title = user.title;
      if (user.avatar && !p.avatar) p.avatar = Live.img(user.avatar);
      return p;
    }
    const slot = freeSlot();
    if (!slot) return null;
    p = makePerson(user);
    p.slot = slot; slot.taken = p.id;
    persons.set(p.id, p);
    const entry = point('entry') || { x: S.aisle?.x ?? W / 2, y: H + 80 };
    if (instant) { p.x = slot.x; p.y = slot.y; p.lastActive = now() - 30000; }
    else {
      const side = slot.x < (S.aisle?.x ?? W / 2) ? -1 : 1;
      p.x = (S.aisle ? S.aisle.x + side * S.aisle.lane : entry.x); p.y = entry.y;
      p.tasks.push({ type: 'walk', pts: (q) => route(q, slot) }, { type: 'pose', pose: 'idle' });
    }
    relayout();
    return p;
  }

  function leave(p) {
    if (p.slot) p.slot.taken = null;
    p.leaving = true; p.fadeStart = now();
  }

  function addNpc(n) {
    const at = point(n.at) || { x: W / 2, y: H / 2 };
    const p = makePerson({ id: 'npc:' + n.id, name: n.name || '', character: n.character }, { npc: true, x: at.x, y: at.y, flip: Boolean(n.flip), showName: n.showName !== false, scale: n.scale || 1, pose: n.pose || 'idle', homePose: n.pose || 'idle', cfg: n });
    p.slot = { x: at.x, y: at.y };
    npcs.set(n.id, p);
  }

  /** Đường đi: dọc làn cạnh lối giữa rồi rẽ vào chỗ (né vật giữa lối như lư hương, sân khấu). */
  function route(p, target) {
    if (!S.aisle) return [{ x: target.x, y: target.y }];
    const ax = S.aisle.x;
    const side = (Math.abs(target.x - ax) < 2 ? p.x : target.x) < ax ? -1 : 1;
    const lx = ax + side * S.aisle.lane;
    return [{ x: lx, y: p.y }, { x: lx, y: target.y }, { x: target.x, y: target.y }];
  }

  function resolveTarget(p, to) {
    if (to === 'home') return p.slot;
    if (to === 'seat') return p.slot;
    return point(to) || (typeof to === 'object' ? to : p.slot);
  }

  // Hàng việc của từng người: walk / pose / play / wait / do
  const P = {
    walkTo(p, to) { p.tasks.push({ type: 'walk', pts: (q) => { const t = resolveTarget(q, to); return t ? (to === 'home' || to === 'seat' ? route(q, t) : route(q, t)) : []; } }); },
    pose(p, pose) { p.tasks.push({ type: 'pose', pose }); },
    play(p, anim, times = 1, onEach) { p.tasks.push({ type: 'play', anim, times, onEach }); },
    wait(p, ms) { p.tasks.push({ type: 'wait', ms }); },
    do(p, fn) { p.tasks.push({ type: 'do', fn }); },
    say(p, text, ms = 6500) { p.bubble = { text: String(text).slice(0, 80), until: now() + ms }; p.lastActive = now(); },
    aura(p, level = 1) { p.aura = Math.max(p.aura, level); },
    boost(p, scale = 1.25, ms = 4000) { p.boost = scale; p.boostUntil = now() + ms; },
    head(p) { const h = height(p); return { x: p.x, y: p.y - h * 1.05, h }; },
  };

  function height(p) {
    const base = G.personH(S, p.y) * (p.char?.scale || 1) * (p.scale || 1);
    return base * (p.boost || 1);
  }

  function update(p, t, dt) {
    if (p.boostUntil && t > p.boostUntil) { p.boost += (1 - p.boost) * Math.min(1, dt / 300); if (Math.abs(p.boost - 1) < 0.01) { p.boost = 1; p.boostUntil = 0; } }
    if (!p.task && p.tasks.length) { p.task = p.tasks.shift(); p.task.start = t; }
    const task = p.task;
    if (task) {
      if (task.type === 'walk') {
        if (typeof task.pts === 'function') task.pts = task.pts(p);
        const target = task.pts[0];
        p.walking = true;
        if (!target) { p.task = null; p.walking = false; }
        else {
          const dx = target.x - p.x, dy = target.y - p.y, dist = Math.hypot(dx, dy);
          const speed = 0.0045 * Math.max(30, G.personH(S, p.y)) * dt;
          if (dist <= speed) { p.x = target.x; p.y = target.y; task.pts.shift(); }
          else { p.x += (dx / dist) * speed; p.y += (dy / dist) * speed; if (Math.abs(dx) > 2) p.faceLeft = dx < 0; p.walkDir = Math.abs(dy) >= Math.abs(dx) ? (dy < 0 ? 'up' : 'down') : 'side'; }
          p.walkPhase = (p.walkPhase || 0) + dt / 140;
        }
      } else if (task.type === 'pose') { p.pose = task.pose; p.anim = null; p.walking = false; p.task = null; }
      else if (task.type === 'play') {
        const a = anims[task.anim] || DEFAULT_ANIMS.bow;
        const k = (t - task.start) / (a.ms || 1000);
        p.walking = false;
        p.anim = { a, k };
        const n = Math.floor(k);
        if (task.onEach && n !== task.last) { task.last = n; if (n < task.times) task.onEach(p, n); }
        if (k >= task.times) { p.anim = null; p.task = null; }
      } else if (task.type === 'wait') { if (t - task.start >= task.ms) p.task = null; }
      else if (task.type === 'do') { p.task = null; try { task.fn(p); } catch (e) { console.error('[Kit.scene] lỗi trong bước "do"', e); } }
    } else {
      p.walking = false;
      // rảnh mà không ở đúng chỗ (chỗ ngồi vừa xếp lại lúc đang đi) thì tự về chỗ
      if (p.slot && !p.leaving && Math.hypot(p.x - p.slot.x, p.y - p.slot.y) > 3) p.tasks.push({ type: 'walk', pts: (q) => route(q, q.slot) }, { type: 'pose', pose: 'idle' });
    }
    if (p.aura > 0) p.aura = Math.max(0, p.aura - dt / 3500);
    if (p.bubble && t > p.bubble.until) p.bubble = null;
  }

  /** Tư thế đang hiện: theo hoạt cảnh nếu đang chạy, theo bước chân nếu đang đi. */
  function currentPose(p) {
    if (p.walking) return 'walk';
    if (p.anim) { const f = p.anim.a.frames; return f[Math.min(f.length - 1, Math.floor((p.anim.k % 1) * f.length))]; }
    return p.pose || 'idle';
  }

  // ---------- Vẽ người ----------
  const STAND_POSES = ['stand', 'walk', 'incense', 'offer', 'sitDown', 'cheer', 'dance1', 'dance2'];
  function drawPerson(p, t) {
    let alpha = 1;
    if (p.leaving) { alpha = 1 - (t - p.fadeStart) / 1200; if (alpha <= 0) { persons.delete(p.id); return; } }
    const h = height(p);
    // "idle@0.8": cùng tư thế nhưng nén thấp xuống (làm động tác cúi khi tờ nhân vật không có khung cúi)
    let pose = currentPose(p), squash = 1;
    if (pose.includes('@')) { const [name, k] = pose.split('@'); pose = name; squash = Number(k) || 1; }
    const c = p.char;
    ctx.save();
    ctx.globalAlpha = alpha;
    if (p.aura > 0) {
      const g = ctx.createRadialGradient(p.x, p.y - h * 0.5, 2, p.x, p.y - h * 0.5, h * 1.1);
      g.addColorStop(0, `rgba(255,220,120,${0.8 * p.aura})`); g.addColorStop(1, 'rgba(255,200,80,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p.x, p.y - h * 0.5, h * 1.1, 0, 6.283); ctx.fill();
    }
    // nệm dưới người đang quỳ / ngồi (scene.json person.cushion); ghế danh dự đã có nệm vẽ sẵn trên nền
    const cu = S.person?.cushion;
    const atVip = p.slot?.vip && Math.hypot(p.x - p.slot.x, p.y - p.slot.y) < 3;
    if (cu && !p.walking && !atVip && p.cfg?.cushion !== false && !(cu.standPoses || STAND_POSES).includes(pose)) {
      const rx = h * (cu.width ?? 0.62), ry = rx * (cu.depth ?? 0.3), cy = p.y - ry * 0.25;
      ctx.fillStyle = 'rgba(0,0,0,.3)'; ctx.beginPath(); ctx.ellipse(p.x, cy + ry * 0.45, rx * 1.04, ry * 1.04, 0, 0, 6.283); ctx.fill();
      const g = ctx.createLinearGradient(0, cy - ry, 0, cy + ry);
      g.addColorStop(0, cu.light || '#c2402c'); g.addColorStop(1, cu.color || '#7a1a12');
      ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(p.x, cy, rx, ry, 0, 0, 6.283); ctx.fill();
      if (cu.rim !== false) { ctx.strokeStyle = cu.rim || 'rgba(232,192,106,.7)'; ctx.lineWidth = Math.max(1, h * 0.025); ctx.beginPath(); ctx.ellipse(p.x, cy, rx * 0.8, ry * 0.8, 0, 0, 6.283); ctx.stroke(); }
    } else {
      ctx.fillStyle = 'rgba(0,0,0,.28)'; ctx.beginPath(); ctx.ellipse(p.x, p.y + 1, h * 0.36, h * 0.1, 0, 0, 6.283); ctx.fill();
    }
    if (squash !== 1) { ctx.translate(p.x, p.y); ctx.scale(1 + (1 - squash) * 0.18, squash); ctx.translate(-p.x, -p.y); }
    const flip = p.walking ? (p.faceLeft ?? p.flip) : p.flip;
    let drawn = false;
    if (c.animD && c.animD.ready && (pose === 'idle' || !c.sheetD)) {
      const d = c.animD, w = h * d.w / d.h;
      d.draw(ctx, p.x - w / 2, p.y - h, w, h, { t: t + (hash(p.id) % 1000), flip });
      drawn = true;
    } else if (c.sheetD && c.sheetD.ready) {
      const poses = c.poses || {};
      let idx = poses[pose];
      if (pose === 'walk') {
        // khung đi theo hướng: walkUp (thấy lưng), walkDown (thấy mặt), walkSide (nghiêng, vẽ quay sang phải); thiếu thì dùng walk
        const dirKey = { up: 'walkUp', down: 'walkDown', side: 'walkSide' }[p.walkDir];
        const w = c[dirKey] || c.walk || [poses.stand ?? poses.idle ?? 0];
        idx = w[Math.floor(p.walkPhase || 0) % w.length];
      }
      if (idx === undefined) idx = poses.idle ?? 0;
      const refBox = c.sheetD.boxes[poses.idle ?? 0];
      const bob = pose === 'walk' ? Math.abs(Math.sin(p.walkPhase || 0)) * h * 0.03 : 0;
      drawn = c.sheetD.drawFrame(ctx, idx, p.x, p.y - bob, h, { refH: refBox.h, flip, t });
    }
    if (!drawn) drawPlaceholder(p, h, pose);
    ctx.restore();
  }

  // Hình người giữ chỗ khi chưa có ảnh nhân vật (áo, đầu, búi tóc; quỳ hoặc đứng theo scene.person.idleStyle)
  function drawPlaceholder(p, h, pose) {
    const kneelBase = (theme.scene?.person?.idleStyle || 'kneel') !== 'stand';
    const standing = pose === 'walk' || pose === 'stand' || pose === 'offer' || pose.startsWith('dance') || pose === 'cheer' || !kneelBase;
    const bow = pose === 'bowFull' ? 1 : pose === 'bowHalf' || pose === 'offer' ? 0.5 : 0;
    const s = h / (standing && kneelBase ? 66 : standing ? 86 : 66);
    ctx.translate(p.x, p.y); ctx.scale(s, s);
    const robe = col('placeholderRobe', `hsl(${220 + p.tint},16%,${62 + p.tint / 2}%)`), dark = `hsl(${220 + p.tint},18%,44%)`;
    const g = ctx.createLinearGradient(-22, 0, 22, 0);
    g.addColorStop(0, dark); g.addColorStop(0.5, robe); g.addColorStop(1, dark);
    ctx.fillStyle = g;
    if (standing) {
      const bob = pose === 'walk' ? Math.abs(Math.sin(p.walkPhase || 0)) * 3 : 0;
      const arm = pose === 'cheer' ? -1 : 0;
      ctx.beginPath(); ctx.moveTo(-20, 0); ctx.lineTo(-13, -58 - bob + bow * 14); ctx.lineTo(13, -58 - bob + bow * 14); ctx.lineTo(20, 0); ctx.closePath(); ctx.fill();
      if (arm) { ctx.fillRect(-18, -80 - bob, 6, 26); ctx.fillRect(12, -80 - bob, 6, 26); }
      head(0, -68 - bob + bow * 26, 0);
    } else {
      const hh = 38 - bow * 18;
      ctx.beginPath(); ctx.moveTo(-23, 0); ctx.quadraticCurveTo(-24, -hh, -10, -hh - 4); ctx.lineTo(10, -hh - 4); ctx.quadraticCurveTo(24, -hh, 23, 0); ctx.closePath(); ctx.fill();
      head(0, -hh - 12 + bow * 4, bow);
    }
  }
  function head(x, y, bow) {
    ctx.fillStyle = '#1d1512';
    ctx.beginPath(); ctx.ellipse(x, y, 10, 11 - bow * 3, 0, 0, 6.283); ctx.fill();
    ctx.beginPath(); ctx.arc(x, y - 9 + bow * 6, 5.5, 0, 6.283); ctx.fill();
  }

  // ---------- Nhãn tên, bong bóng chat ----------
  // Dùng chung cho cảnh 2D và 3D (Kit.makeLabels): head(p) trả toạ độ đầu trên khung 1080 x 1920.
  function makeLabels({ head, color = (k, d) => d, maxTags: tagsOf = () => 8 }) {
    let ctx = null;
    function roundRect(x, y, w, h, r) {
      ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
    }

    // Nhãn tên: top 3 trên ghế, người vừa tặng / chat / đang làm hành động, rồi người mới vào.
    // Tối đa maxTags nhãn (scene.json "maxTags", không tính top 3) và không cho nhãn đè lên nhau.
    function tagRect(p) {
      const hd = head(p);
      ctx.font = '700 27px "Be Vietnam Pro", system-ui, sans-serif';
      const w = ctx.measureText(p.name.slice(0, 14)).width + 62;
      const top = hd.y - 40 - (p.bubble ? 96 : 0);
      return { x: hd.x - w / 2 - 4, y: top - 4, w: Math.max(w, p.bubble ? 320 : 0) + 8, h: hd.y - top + 8 };
    }
    function pickTags(all, t) {
      const cand = [];
      for (const p of all) {
        p.showTag = false;
        if (p.leaving) continue;
        if (p.npc) { p.showTag = p.showName; continue; }
        const vip = p.slot?.vip && p.rank > 0 && p.rank <= 3;
        const acting = (p.task || p.tasks.length) && p.lastActive > p.joinedAt && t - p.lastActive < 30000;
        const recent = p.bubble || t - p.lastActive < 9000 || acting;
        const fresh = t - p.joinedAt < 5000;
        if (vip || recent || fresh) cand.push({ p, pri: vip ? 0 : recent ? 1 : 2 });
      }
      cand.sort((a, b) => a.pri - b.pri || b.p.lastActive - a.p.lastActive || b.p.joinedAt - a.p.joinedAt);
      const placed = [];
      let n = 0;
      ctx.save();
      for (const { p, pri } of cand) {
        if (pri > 0 && n >= tagsOf()) break;
        const r = tagRect(p);
        if (placed.some((q) => r.x < q.x + q.w && r.x + r.w > q.x && r.y < q.y + q.h && r.y + r.h > q.y)) continue;
        placed.push(r);
        p.showTag = true;
        if (pri > 0) n++;
      }
      ctx.restore();
    }

    function drawTag(p) {
      const hd = head(p);
      if (!p.showTag) { if (p.npc && p.bubble) drawBubble(hd.x, hd.y - 2, p.bubble.text); return; }
      if (p.bubble) drawBubble(hd.x, hd.y - 44, p.bubble.text);
      ctx.save();
      ctx.font = '700 27px "Be Vietnam Pro", system-ui, sans-serif';
      const medal = ['', '🥇 ', '🥈 ', '🥉 '][p.rank] || '';
      const name = medal + (p.name.length > 14 ? p.name.slice(0, 13) + '…' : p.name);
      const w = ctx.measureText(name).width + (p.npc ? 24 : 56), h = 40;
      const x = Math.max(4, Math.min(W - w - 4, hd.x - w / 2)), y = hd.y - h;
      ctx.globalAlpha = p.leaving ? 0 : 0.94;
      ctx.fillStyle = color('tagBg', 'rgba(25,14,10,.8)'); roundRect(x, y, w, h, 8); ctx.fill();
      ctx.strokeStyle = color('tagBorder', 'rgba(214,168,82,.55)'); ctx.lineWidth = 1; ctx.stroke();
      if (!p.npc) {
        ctx.save(); ctx.beginPath(); ctx.arc(x + 21, y + h / 2, 15, 0, 6.283); ctx.clip();
        if (p.avatar && p.avatar.complete && p.avatar.naturalWidth) ctx.drawImage(p.avatar, x + 6, y + h / 2 - 15, 30, 30);
        else { ctx.fillStyle = '#8a7a6a'; ctx.fill(); }
        ctx.restore();
      }
      ctx.fillStyle = color('tagText', '#fff'); ctx.textBaseline = 'middle';
      ctx.fillText(name, x + (p.npc ? 12 : 42), y + h / 2 + 1);
      ctx.restore();
    }

    function drawBubble(cx, bottom, text) {
      ctx.save();
      ctx.font = '600 28px "Be Vietnam Pro", system-ui, sans-serif';
      const words = String(text).split(/\s+/), lines = [];
      let line = '';
      for (const w of words) { const t = line ? line + ' ' + w : w; if (ctx.measureText(t).width > 290 && line) { lines.push(line); line = w; } else line = t; }
      if (line) lines.push(line);
      if (lines.length > 2) { lines.length = 2; lines[1] = lines[1].slice(0, 20) + '…'; }
      const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 32, h = lines.length * 34 + 20;
      const x = Math.max(6, Math.min(W - w - 6, cx - w / 2)), y = bottom - h;
      ctx.fillStyle = color('bubbleBg', 'rgba(30,22,20,.86)'); roundRect(x, y, w, h, 12); ctx.fill();
      ctx.fillStyle = color('bubbleText', '#fff'); ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      lines.forEach((l, i) => ctx.fillText(l, x + w / 2, y + 11 + i * 34));
      ctx.restore();
    }
    return {
      pick(c, all, t) { ctx = c; pickTags(all, t); },
      draw(c, p) { ctx = c; drawTag(p); },
      bubble(c, cx, bottom, text) { ctx = c; drawBubble(cx, bottom, text); },
    };
  }
  K.makeLabels = makeLabels;
  const labels = makeLabels({ head: (p) => P.head(p), color: col, maxTags: () => maxTags });

  // ---------- Ghế danh dự: top N người tặng nhiều nhất ----------
  // Sıra → koltuk: `top` dizisindeki i. kişi (0 tabanlı, sunucunun verdiği sırayla) HER ZAMAN seats[i]'ye oturur.
  // Sıralama değişirse kişiler yer değiştirir; top'tan düşen koltuğu boşaltır.
  function seatTop(top = []) {
    if (!seats.length) return;
    const want = top.slice(0, seats.length);
    const rankIdx = new Map(want.map((u, i) => [u.id, i]));
    // 1) Koltuğu sırasına uymayan herkesi kaldır (sıra değiştiyse bir sonraki adımda doğru koltuğa yürür)
    seats.forEach((seat, i) => {
      if (!seat.taken || rankIdx.get(seat.taken) === i) return;
      const p = persons.get(seat.taken);
      seat.taken = null;
      if (!p || p.leaving) return;
      const s = freeSlot();
      if (!s) { leave(p); return; }
      p.slot = s; s.taken = p.id;
      P.walkTo(p, 'home'); P.pose(p, 'idle');
    });
    // 2) Sırayla oturt: seats[0], seats[1], ...
    want.forEach((u, i) => {
      const p = persons.get(u.id) || ensure({ ...u, isPlayer: true });
      if (!p || p.leaving) return;
      p.rank = u.rank || i + 1; p.coins = u.coins;
      const seat = seats[i];
      if (p.slot === seat || seat.taken) return;
      if (p.task || p.tasks.length) return; // meşgul: sonraki state güncellemesinde oturur
      if (p.slot) p.slot.taken = null;
      p.slot = seat; seat.taken = p.id;
      P.walkTo(p, 'seat'); P.pose(p, 'idle');
      P.do(p, (q) => { q.aura = 1; K.fx.pillar(q.x, q.y, { height: height(q) * 6 }); K.events?.emit('seated', q); });
    });
  }

  /** Đổi nhân vật khi chat đúng từ khoá của một mẫu người (1–3 từ, ví dụ "bà", "cao tăng"). */
  function skinFromChat(user, text) {
    const w = String(text || '').toLowerCase().normalize('NFC').replace(/[^\p{L}\s]/gu, ' ').replace(/\s+/g, ' ').trim();
    if (!w || w.split(' ').length > 3) return false;
    const c = chars.find((x) => (x.keywords || []).some((k) => w === k.toLowerCase()));
    const p = persons.get(user.id);
    if (!c || !p || p.char === c) return false;
    p.char = c; p.aura = 0.8;
    K.fx.emit('spark', { x: p.x, y: p.y - height(p) * 0.6, count: 10, spread: 20 });
    return true;
  }

  // ---------- Camera ----------
  /** Zoom vào người / điểm trong `duration` ms rồi quay về toàn cảnh. Nhiều yêu cầu thì xếp hàng. */
  function focus(target, o = {}) {
    if (settings.cameraFx === false) return;
    cam.queue.push({ target, zoom: o.zoom ?? 1.55, ms: o.duration ?? 3200 });
    if (cam.queue.length > 4) cam.queue.splice(1, cam.queue.length - 4);
  }

  function updateCamera(t, dt) {
    if (t > cam.until && cam.queue.length) { cam.cur = cam.queue.shift(); cam.until = t + cam.cur.ms; }
    if (cam.cur && t <= cam.until) {
      const tg = typeof cam.cur.target === 'function' ? cam.cur.target() : cam.cur.target?.id ? persons.get(cam.cur.target.id) || cam.cur.target : cam.cur.target;
      if (tg) { cam.tx = tg.x; cam.ty = tg.y - (tg.npc || tg.slot ? height(tg) * 0.8 : 0); cam.tz = cam.cur.zoom; }
    } else { cam.cur = null; cam.tx = W / 2; cam.ty = H / 2; cam.tz = 1; }
    const k = Math.min(1, dt / 350);
    cam.z += (cam.tz - cam.z) * k; cam.x += (cam.tx - cam.x) * k; cam.y += (cam.ty - cam.y) * k;
    const hw = W / (2 * cam.z), hh = H / (2 * cam.z);
    cam.x = Math.max(hw, Math.min(W - hw, cam.x)); cam.y = Math.max(hh, Math.min(H - hh, cam.y));
  }

  // ---------- Nền ----------
  const chromaParam = new URLSearchParams(location.search).has('chroma');
  function drawBackground(t) {
    // nền xanh để ghép trong OBS (cài đặt "chroma" hoặc ?chroma): bỏ ảnh nền, đèn lung linh, tia nắng
    if (settings.chroma === true || chromaParam) { ctx.fillStyle = theme.scene?.chroma || '#00ff00'; ctx.fillRect(0, 0, W, H); return; }
    const d = bgVideo && bgVideo.ready ? bgVideo : bgImage && bgImage.ready ? bgImage : null;
    if (d) {
      const s = Math.max(W / d.w, H / d.h);
      d.draw(ctx, (W - d.w * s) / 2, (H - d.h * s) / 2, d.w * s, d.h * s, { t });
    } else {
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, col('placeholderTop', '#2a2f45')); g.addColorStop(S.horizonY / H, col('placeholderMid', '#3b4160')); g.addColorStop(1, col('placeholderFloor', '#1b1e2c'));
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
      if (theme.scene?.hint !== false) { // scene.json "hint": false → yayında ızgara ve yardım yazısı görünmez
        ctx.strokeStyle = 'rgba(255,255,255,.08)'; ctx.lineWidth = 2;
        for (let x = -800; x <= W + 800; x += 90) { ctx.beginPath(); ctx.moveTo(W / 2 + (x - W / 2) * 0.05, S.horizonY); ctx.lineTo(x, H); ctx.stroke(); }
        ctx.fillStyle = 'rgba(255,255,255,.55)'; ctx.font = '600 30px system-ui'; ctx.textAlign = 'center';
        ctx.fillText(theme.scene?.background ? `Arka plan bulunamadı: ${theme.scene.background}` : "Arka plan görselini assets/ klasörüne koyup scene.json'da tanımlayın", W / 2, S.floor.top - 110);
      }
    }
    for (const [x, y, r] of theme.scene?.glows || []) {
      const f = 0.75 + 0.25 * Math.sin(t / 110 + x) * Math.sin(t / 47 + y);
      ctx.save(); ctx.globalCompositeOperation = 'lighter';
      const g = ctx.createRadialGradient(x, y, 0, x, y, (r || 20) * f);
      g.addColorStop(0, `rgba(255,200,120,${0.35 * f})`); g.addColorStop(1, 'rgba(255,160,60,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, (r || 20) * f, 0, 6.283); ctx.fill(); ctx.restore();
    }
    if (settings.ambientFx !== false && theme.scene?.sunrays) drawSunRays(t, theme.scene.sunrays);
  }

  function drawSunRays(t, cfg) {
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    const a = (cfg.alpha ?? 0.05) + 0.025 * Math.sin(t / 2600);
    const from = cfg.from ?? 1060, dir = from > W / 2 ? -1 : 1;
    for (const [dx, w] of [[0, 70], [-80, 40], [60, 50]]) {
      const x0 = from + dx;
      const g = ctx.createLinearGradient(x0, 0, x0 + dir * 520, cfg.length ?? 980);
      g.addColorStop(0, `rgba(255,226,160,${a})`); g.addColorStop(1, 'rgba(255,226,160,0)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.moveTo(x0, -20); ctx.lineTo(x0 + w, -20); ctx.lineTo(x0 + dir * 520 + w * 2.2, cfg.length ?? 980); ctx.lineTo(x0 + dir * 520, cfg.length ?? 980); ctx.closePath(); ctx.fill();
    }
    ctx.restore();
  }

  // ---------- Vòng vẽ ----------
  let debugOverlay = new URLSearchParams(location.search).has('scene');
  function frame(t, dt) {
    if (!ctx) return;
    relayout();
    maintainFill(t);
    updateCamera(t, dt);
    K.fx.update(dt, t);
    const all = [...persons.values(), ...npcs.values(), ...fillers.values()];
    for (const p of all) update(p, t, dt);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const sh = K.fx.shakeOffset(t);
    ctx.setTransform(cam.z, 0, 0, cam.z, W / 2 - cam.x * cam.z + sh.x, H / 2 - cam.y * cam.z + sh.y);
    drawBackground(t);
    K.fx.draw(ctx, 'back', t);
    all.sort((a, b) => a.y - b.y);
    for (const p of all) drawPerson(p, t);
    K.fx.draw(ctx, 'front', t);
    K.fx.draw(ctx, 'top', t);
    labels.pick(ctx, all, t);
    for (let i = all.length - 1; i >= 0; i--) if (!all[i].leaving || persons.has(all[i].id)) labels.draw(ctx, all[i]);
    if (debugOverlay) drawDebug();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    K.fx.draw(ctx, 'screen', t);
  }

  // ?scene: vẽ đè vùng sàn, lối đi, chỗ đứng, ghế, điểm để kiểm tra scene.json
  function drawDebug() {
    ctx.save();
    ctx.strokeStyle = 'rgba(0,255,200,.9)'; ctx.lineWidth = 3; ctx.setLineDash([12, 8]);
    ctx.strokeRect(S.floor.left, S.floor.top, S.floor.right - S.floor.left, S.floor.bottom - S.floor.top);
    ctx.beginPath(); ctx.moveTo(0, S.horizonY); ctx.lineTo(W, S.horizonY); ctx.stroke();
    ctx.setLineDash([]);
    if (S.aisle) for (let y = S.floor.top; y < H; y += 40) { const hw = G.aisleHalf(S, y); ctx.fillStyle = 'rgba(255,80,80,.35)'; ctx.fillRect(S.aisle.x - hw, y, hw * 2, 3); }
    ctx.fillStyle = 'rgba(0,255,200,.7)';
    for (const s of layout.slots) { ctx.beginPath(); ctx.arc(s.x, s.y, 4, 0, 6.283); ctx.fill(); }
    ctx.fillStyle = 'rgba(255,215,0,.9)';
    for (const s of seats) { ctx.beginPath(); ctx.arc(s.x, s.y, 8, 0, 6.283); ctx.fill(); }
    ctx.fillStyle = 'rgba(255,0,180,.9)'; ctx.font = '700 22px system-ui';
    for (const [name, v] of Object.entries(theme.scene?.points || {})) { const p = point(name); ctx.beginPath(); ctx.arc(p.x, p.y, 9, 0, 6.283); ctx.fill(); ctx.fillText(name, p.x + 12, p.y - 10); }
    for (const o of S.obstacles) { ctx.fillStyle = 'rgba(255,60,60,.25)'; ctx.fillRect(o.x0, o.y0, o.x1 - o.x0, o.y1 - o.y0); }
    ctx.restore();
  }

  function reset() { for (const p of persons.values()) leave(p); for (const s of seats) s.taken = null; fillAt = 0; }

  K.scene = {
    init, configure, frame, ensure, leave: (id) => { const p = persons.get(id); if (p) leave(p); }, reset, point, seatTop, skinFromChat, focus,
    person: (id) => persons.get(id), npc: (id) => npcs.get(id), people: () => [...persons.values()].filter((p) => !p.leaving),
    extras: () => [...fillers.values()], // người lấp chỗ (không phải người xem)
    height, P, get layout() { return layout; }, get seats() { return seats; }, get scene() { return S; }, get chars() { return chars; },
    set debug(v) { debugOverlay = v; },
  };
})();
