// Kit.fx: thư viện hiệu ứng vẽ trên canvas. Mọi hiệu ứng nhận ảnh của theme (png / gif / webm / lottie)
// qua tham số `image`; không có ảnh thì vẽ bằng hình mặc định.
//
//   Kit.fx.emit('petal', { x, y, count: 20 })            hạt: smoke heart spark petal confetti snow leaf bubble firefly ember coin star
//   Kit.fx.emitter('khoi', 'smoke', { x, y, every: 70 }) phát liên tục (dừng: Kit.fx.stop('khoi'))
//   Kit.fx.rain('petal', { count: 40, duration: 4000 })  rơi từ trên xuống cả màn hình
//   Kit.fx.halo(x, y, { radius, image })   Kit.fx.rays({ x, y })   Kit.fx.pillar(x, y)
//   Kit.fx.text(x, y, '+1 công đức')       Kit.fx.spotlight(person)   Kit.fx.fireworks({ bursts: 5 })
//   Kit.fx.sprite('assets/fx/halo.png', { x, y, w, h, duration, blend: 'screen' })
//   Kit.fx.fly('lotus', from, to, { count: 6 })   Kit.fx.flash()   Kit.fx.shake()
//   Kit.fx.beat.bpm = 128; Kit.fx.beat.pulse(t) → 0..1 theo nhịp nhạc

(function () {
  const A = () => window.Kit.assets;
  const rand = (a, b) => a + Math.random() * (b - a);
  const items = [];          // hạt + hiệu ứng có thời hạn
  const emitters = new Map();
  const W = () => window.Kit.W || 1080, H = () => window.Kit.H || 1920;

  // ---------- Kiểu hạt mặc định ----------
  const PRESETS = {
    smoke:    { life: [3200, 4600], size: [10, 15], grow: 2.2, vy: [-80, -55], vx: [-6, 6], sway: 6, alpha: 0.6, color: '255,252,246', shape: 'puff', layer: 'front' },
    heart:    { life: [1300, 2000], size: [16, 24], vy: [-160, -100], vx: [-30, 30], alpha: 1, shape: 'heart', color: '255,70,110' },
    spark:    { life: [800, 1600], size: [3, 7], vy: [-110, -30], vx: [-35, 35], alpha: 1, shape: 'dot', color: '255,236,170', glow: true, blend: 'lighter' },
    petal:    { life: [4000, 6500], size: [8, 14], vy: [80, 170], vx: [-30, 30], sway: 40, spin: [-2, 2], alpha: 0.95, shape: 'petal', color: '243,154,194' },
    confetti: { life: [3000, 5000], size: [8, 14], vy: [140, 260], vx: [-60, 60], sway: 30, spin: [-6, 6], alpha: 1, shape: 'rect', palette: ['255,99,132', '255,205,86', '75,192,192', '54,162,235', '153,102,255', '255,255,255'] },
    snow:     { life: [5000, 8000], size: [3, 7], vy: [40, 90], vx: [-15, 15], sway: 25, alpha: 0.9, shape: 'dot', color: '255,255,255' },
    leaf:     { life: [4500, 7000], size: [10, 16], vy: [70, 140], vx: [-40, 40], sway: 50, spin: [-3, 3], alpha: 0.95, shape: 'petal', palette: ['214,120,40', '200,80,30', '120,150,50', '230,170,60'] },
    bubble:   { life: [2500, 4000], size: [8, 18], vy: [-90, -50], vx: [-20, 20], sway: 15, alpha: 0.7, shape: 'ring', color: '200,240,255' },
    firefly:  { life: [3000, 6000], size: [3, 5], vy: [-20, 20], vx: [-20, 20], sway: 30, alpha: 1, shape: 'dot', color: '255,240,140', glow: true, blend: 'lighter', twinkle: true },
    ember:    { life: [1200, 2400], size: [2, 5], vy: [-160, -80], vx: [-25, 25], sway: 20, alpha: 1, shape: 'dot', color: '255,150,60', glow: true, blend: 'lighter' },
    coin:     { life: [1500, 2500], size: [12, 18], vy: [-320, -200], vx: [-120, 120], gravity: 600, alpha: 1, shape: 'coin', color: '255,200,60', spin: [6, 12] },
    star:     { life: [900, 1800], size: [8, 14], vy: [-60, -10], vx: [-30, 30], alpha: 1, shape: 'star', color: '255,230,140', glow: true, blend: 'lighter', twinkle: true },
  };

  /** Thêm hoặc ghi đè kiểu hạt (theme tự định nghĩa, ví dụ bong bóng xà phòng có ảnh riêng). */
  function preset(name, cfg) { PRESETS[name] = { ...(PRESETS[name] || {}), ...cfg }; }

  const pickR = (v) => (Array.isArray(v) ? rand(v[0], v[1]) : v ?? 0);

  function emit(name, o = {}) {
    const p = { ...(PRESETS[name] || PRESETS.spark), ...o };
    const n = Math.min(400, o.count ?? 1);
    const k = o.strong ? 1.4 : 1;
    for (let i = 0; i < n; i++) {
      items.push({
        type: 'particle', p, born: performance.now() + (o.stagger ? i * o.stagger : 0),
        life: pickR(p.life), x: (o.x ?? W() / 2) + rand(-(o.spread ?? 10), o.spread ?? 10), y: (o.y ?? H() / 2) + rand(-(o.spreadY ?? o.spread ?? 10) / 2, (o.spreadY ?? o.spread ?? 10) / 2),
        vx: pickR(p.vx) * k, vy: pickR(p.vy) * k, size: pickR(p.size) * (o.scale ?? 1) * k, rot: rand(0, 6.28), vr: pickR(p.spin),
        color: p.palette ? p.palette[(Math.random() * p.palette.length) | 0] : p.color, phase: rand(0, 6.28),
        image: o.image ? A().get(o.image) : p.image ? A().get(p.image) : null,
      });
    }
  }

  function emitter(id, name, o = {}) { emitters.set(id, { name, o, acc: 0 }); }
  function stop(id) { emitters.delete(id); }

  function rain(name, o = {}) {
    const count = o.count ?? 40, dur = o.duration ?? 3000;
    for (let i = 0; i < count; i++) {
      items.push({ type: 'delay', at: performance.now() + Math.random() * dur, fn: () => emit(name, { ...o, count: 1, x: rand(o.x0 ?? 0, o.x1 ?? W()), y: rand(-80, -10), spread: 0 }) });
    }
  }

  // ---------- Hiệu ứng có thời hạn ----------
  const add = (type, o) => { items.push({ type, born: performance.now(), life: o.duration ?? 2000, ...o }); };

  function halo(x, y, o = {}) { add('halo', { x, y, r: o.radius ?? 180, color: o.color ?? '255,214,120', image: o.image ? A().get(o.image) : null, duration: o.duration ?? 2600, layer: o.layer ?? 'back' }); }
  function rays(o = {}) { add('rays', { x: o.x ?? W() / 2, y: o.y ?? 300, color: o.color ?? '255,220,140', n: o.count ?? 9, duration: o.duration ?? 5000, layer: 'back', image: o.image ? A().get(o.image) : null }); }
  function pillar(x, y, o = {}) { add('pillar', { x, y, h: o.height ?? 600, w: o.width ?? 70, color: o.color ?? '255,226,150', duration: o.duration ?? 1800, layer: 'back' }); }
  function text(x, y, str, o = {}) { add('text', { x, y, str: String(str), color: o.color ?? '#ffe39a', size: o.size ?? 34, duration: o.duration ?? 1600, layer: 'top' }); }
  function flash(o = {}) { add('flash', { color: o.color ?? '255,240,200', duration: o.duration ?? 600, strength: o.strength ?? 0.5, layer: 'screen' }); }
  function shake(o = {}) { add('shake', { amp: o.intensity ?? 10, duration: o.duration ?? 500, layer: 'none' }); }

  /** Đèn tiêu điểm: cả cảnh tối đi, vùng sáng bám theo `target` ({ x, y, h }). */
  function spotlight(target, o = {}) { add('spot', { target, color: o.color ?? '255,236,190', r: o.radius ?? 140, dim: o.dim ?? 0.55, duration: o.duration ?? 4000, layer: 'top' }); }

  /** Ảnh hiệu ứng (png / gif / webm / lottie) hiện tại chỗ, to dần, mờ dần. */
  function sprite(url, o = {}) {
    add('sprite', {
      d: A().get(url), x: o.x ?? W() / 2, y: o.y ?? H() / 2, w: o.w, h: o.h, duration: o.duration ?? 2500, blend: o.blend,
      from: { scale: 0.6, alpha: 0, rot: 0, ...(o.from || {}) }, to: { scale: 1.1, alpha: 0, rot: 0, ...(o.to || {}) }, peak: o.peak ?? 0.25, layer: o.layer ?? 'front',
    });
  }

  /** Bay theo vòng cung từ `from` tới `to` (ảnh hoặc kiểu hạt có sẵn). */
  function fly(what, from, to, o = {}) {
    const n = o.count ?? 1;
    for (let i = 0; i < n; i++) {
      add('fly', {
        d: /\.[a-z0-9]+$/i.test(what) ? A().get(what) : null, preset: PRESETS[what] ? what : 'petal',
        sx: from.x + rand(-20, 20), sy: from.y, tx: to.x + rand(-(o.spreadTo ?? 120), o.spreadTo ?? 120), ty: to.y + rand(-15, 15),
        arc: o.arc ?? 180, size: o.size ?? 26, duration: (o.duration ?? 2200) + i * 90, delay: i * (o.stagger ?? 110), layer: 'front',
      });
    }
  }

  /** Pháo hoa nhiều màu + pháo lạnh sân khấu (vòi phun tia sáng) bắn từng cặp. */
  function fireworks(o = {}) {
    const bursts = o.bursts ?? 4, now = performance.now();
    for (let i = 0; i < bursts; i++) {
      items.push({ type: 'delay', at: now + i * 450 + Math.random() * 200, fn: () => {
        const x = rand(160, W() - 160), y = rand(180, H() * 0.42), hue = Math.random() * 360;
        for (let k = 0; k < 70; k++) {
          const a = (k / 70) * 6.283, sp = rand(180, 360);
          items.push({ type: 'particle', p: { shape: 'dot', glow: true, blend: 'lighter', alpha: 1, gravity: 90, drag: 0.985 }, born: performance.now(), life: rand(1100, 1700), x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, size: rand(2, 4), color: hsl(hue + rand(-20, 20)), phase: 0, rot: 0, vr: 0 });
        }
      } });
    }
    const fountains = o.fountains ?? 2;
    for (let i = 0; i < fountains; i++) {
      const xs = [W() * 0.12, W() * 0.88, W() * 0.3, W() * 0.7];
      const x = xs[i % xs.length], y = o.fountainY ?? H() * 0.62;
      add('fountain', { x, y, duration: o.fountainMs ?? 3500, acc: 0, layer: 'front' });
    }
  }
  const hsl = (h) => { const c = (n) => Math.round(255 * Math.max(0, Math.min(1, Math.abs(((h / 60 + n) % 6) - 3) - 1))); return `${c(0)},${c(4)},${c(2)}`; };

  // ---------- Nhịp nhạc ----------
  const beat = {
    bpm: 0, start: performance.now(),
    pulse(t = performance.now()) { if (!this.bpm) return 0; const ph = (((t - this.start) / 60000) * this.bpm) % 1; return Math.pow(1 - ph, 3); },
    bar(t = performance.now()) { return this.bpm ? Math.floor((((t - this.start) / 60000) * this.bpm) / 4) : 0; },
  };

  // ---------- Cập nhật + vẽ ----------
  function update(dt, now) {
    for (const [, e] of emitters) {
      e.acc += dt;
      const every = e.o.every ?? 100;
      while (e.acc >= every) { e.acc -= every; emit(e.name, { ...e.o, count: e.o.count ?? 1 }); }
    }
    const s = dt / 1000;
    for (let i = items.length - 1; i >= 0; i--) {
      const it = items[i];
      if (it.type === 'delay') { if (now >= it.at) { items.splice(i, 1); it.fn(); } continue; }
      const age = now - it.born - (it.delay || 0);
      if (age < 0) continue;
      if (age > it.life) { items.splice(i, 1); continue; }
      if (it.type === 'particle') {
        const p = it.p;
        it.vy += (p.gravity || 0) * s;
        if (p.drag) { it.vx *= p.drag; it.vy *= p.drag; }
        it.x += (it.vx + (p.sway ? Math.sin(now / 600 + it.phase) * p.sway : 0)) * s;
        it.y += it.vy * s;
        it.rot += (it.vr || 0) * s;
      } else if (it.type === 'fountain') {
        it.acc += dt;
        while (it.acc > 18) {
          it.acc -= 18;
          items.push({ type: 'particle', p: { shape: 'streak', glow: true, blend: 'lighter', alpha: 1, gravity: 520 }, born: now, life: rand(900, 1400), x: it.x + rand(-6, 6), y: it.y, vx: rand(-70, 70), vy: rand(-760, -560), size: rand(2, 3.5), color: Math.random() < 0.5 ? '255,244,200' : '255,200,90', phase: 0, rot: 0, vr: 0 });
        }
      }
    }
  }

  /** Độ rung màn hình hiện tại (scene cộng vào camera). */
  function shakeOffset(now) {
    let x = 0, y = 0;
    for (const it of items) if (it.type === 'shake') { const k = 1 - (now - it.born) / it.life; if (k > 0) { x += (Math.random() - 0.5) * it.amp * k; y += (Math.random() - 0.5) * it.amp * k; } }
    return { x, y };
  }

  function draw(ctx, layer, now) {
    for (const it of items) {
      if (it.type === 'delay' || it.type === 'shake' || it.type === 'fountain') continue;
      const age = now - it.born - (it.delay || 0);
      if (age < 0) continue;
      const k = age / it.life;
      const lay = it.type === 'particle' ? (it.p.layer || 'front') : it.layer;
      if (lay !== layer) continue;
      ctx.save();
      DRAW[it.type]?.(ctx, it, k, now);
      ctx.restore();
    }
  }

  const DRAW = {
    particle(ctx, it, k, now) {
      const p = it.p;
      let a = (p.alpha ?? 1) * (p.shape === 'puff' ? Math.sin(Math.PI * Math.min(1, k * 1.15 + 0.06)) : 1 - Math.pow(k, 3));
      if (p.twinkle) a *= 0.5 + 0.5 * Math.sin(now / 120 + it.phase);
      ctx.globalAlpha = Math.max(0, Math.min(1, a));
      if (p.blend) ctx.globalCompositeOperation = p.blend;
      const sz = it.size * (1 + k * (p.grow || 0));
      if (it.image && it.image.ready) {
        ctx.translate(it.x, it.y); ctx.rotate(it.rot);
        const ratio = it.image.h / it.image.w || 1;
        it.image.draw(ctx, -sz, -sz * ratio, sz * 2, sz * 2 * ratio, { t: now });
        return;
      }
      const c = it.color || '255,255,255';
      if (p.glow) { ctx.shadowColor = `rgba(${c},1)`; ctx.shadowBlur = sz * 3; }
      switch (p.shape) {
        case 'puff': { const g = ctx.createRadialGradient(it.x, it.y, 0, it.x, it.y, sz); g.addColorStop(0, `rgba(${c},.95)`); g.addColorStop(0.5, `rgba(${c},.45)`); g.addColorStop(1, `rgba(${c},0)`); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(it.x, it.y, sz, 0, 6.283); ctx.fill(); break; }
        case 'heart': ctx.fillStyle = `rgb(${c})`; heart(ctx, it.x, it.y, sz); break;
        case 'petal': ctx.translate(it.x, it.y); ctx.rotate(it.rot); ctx.fillStyle = `rgb(${c})`; ctx.beginPath(); ctx.ellipse(0, 0, sz, sz / 2, 0, 0, 6.283); ctx.fill(); break;
        case 'rect': ctx.translate(it.x, it.y); ctx.rotate(it.rot); ctx.fillStyle = `rgb(${c})`; ctx.fillRect(-sz / 2, -sz / 4, sz, sz / 2); break;
        case 'ring': ctx.strokeStyle = `rgba(${c},.9)`; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(it.x, it.y, sz, 0, 6.283); ctx.stroke(); break;
        case 'coin': ctx.translate(it.x, it.y); ctx.scale(Math.abs(Math.cos(it.rot)) + 0.1, 1); ctx.fillStyle = `rgb(${c})`; ctx.beginPath(); ctx.arc(0, 0, sz / 2, 0, 6.283); ctx.fill(); ctx.strokeStyle = 'rgba(160,110,20,.9)'; ctx.lineWidth = 2; ctx.stroke(); break;
        case 'star': ctx.fillStyle = `rgb(${c})`; star(ctx, it.x, it.y, sz); break;
        case 'streak': ctx.strokeStyle = `rgba(${c},1)`; ctx.lineWidth = sz; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(it.x, it.y); ctx.lineTo(it.x - it.vx * 0.03, it.y - it.vy * 0.03); ctx.stroke(); break;
        default: ctx.fillStyle = `rgb(${c})`; ctx.beginPath(); ctx.arc(it.x, it.y, sz, 0, 6.283); ctx.fill();
      }
    },
    halo(ctx, it, k, now) {
      const a = Math.sin(Math.PI * k), r = it.r * (0.7 + 0.5 * k);
      ctx.globalCompositeOperation = 'lighter';
      if (it.image?.ready) { ctx.globalAlpha = a; ctx.translate(it.x, it.y); ctx.rotate(now / 3000); it.image.draw(ctx, -r, -r, r * 2, r * 2, { t: now }); return; }
      const g = ctx.createRadialGradient(it.x, it.y, r * 0.2, it.x, it.y, r);
      g.addColorStop(0, `rgba(${it.color},${0.55 * a})`); g.addColorStop(1, `rgba(${it.color},0)`);
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(it.x, it.y, r, 0, 6.283); ctx.fill();
      ctx.strokeStyle = `rgba(${it.color},${0.8 * a})`; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(it.x, it.y, r * 0.62, 0, 6.283); ctx.stroke();
    },
    rays(ctx, it, k, now) {
      const a = Math.sin(Math.PI * Math.min(1, k * 1.3)) * 0.14;
      ctx.globalCompositeOperation = 'lighter';
      if (it.image?.ready) { ctx.globalAlpha = a * 6; it.image.draw(ctx, 0, 0, W(), H() * 0.7, { t: now }); return; }
      for (let i = 0; i < it.n; i++) {
        const ang = Math.PI / 2 + (i - (it.n - 1) / 2) * 0.17 + Math.sin(now / 1300 + i) * 0.03;
        ctx.fillStyle = `rgba(${it.color},${a})`;
        ctx.beginPath(); ctx.moveTo(it.x, it.y);
        ctx.lineTo(it.x + Math.cos(ang - 0.05) * 2200, it.y + Math.sin(ang - 0.05) * 2200);
        ctx.lineTo(it.x + Math.cos(ang + 0.05) * 2200, it.y + Math.sin(ang + 0.05) * 2200);
        ctx.fill();
      }
    },
    pillar(ctx, it, k) {
      const a = Math.sin(Math.PI * k);
      ctx.globalCompositeOperation = 'lighter';
      const g = ctx.createLinearGradient(it.x - it.w, 0, it.x + it.w, 0);
      g.addColorStop(0, `rgba(${it.color},0)`); g.addColorStop(0.5, `rgba(${it.color},${0.55 * a})`); g.addColorStop(1, `rgba(${it.color},0)`);
      ctx.fillStyle = g; ctx.fillRect(it.x - it.w, it.y - it.h, it.w * 2, it.h);
    },
    text(ctx, it, k) {
      ctx.globalAlpha = 1 - Math.pow(k, 2);
      ctx.font = `800 ${it.size}px "Be Vietnam Pro", system-ui, sans-serif`;
      ctx.textAlign = 'center'; ctx.lineWidth = 6; ctx.strokeStyle = 'rgba(0,0,0,.7)'; ctx.fillStyle = it.color;
      const y = it.y - k * 90;
      ctx.strokeText(it.str, it.x, y); ctx.fillText(it.str, it.x, y);
    },
    flash(ctx, it, k) { ctx.fillStyle = `rgba(${it.color},${it.strength * (1 - k)})`; ctx.fillRect(0, 0, W(), H()); },
    spot(ctx, it, k) {
      const t = typeof it.target === 'function' ? it.target() : it.target;
      if (!t) return;
      const a = it.dim * Math.min(1, Math.min(k, 1 - k) * 6);
      const cy = t.y - (t.h || 60) / 2, r = Math.max(it.r, (t.h || 60) * 1.4);
      const g = ctx.createRadialGradient(t.x, cy, r * 0.35, t.x, cy, r);
      g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, `rgba(0,0,0,${a})`);
      ctx.fillStyle = g; ctx.fillRect(0, 0, W(), H());
      ctx.globalCompositeOperation = 'lighter';
      const cone = ctx.createLinearGradient(t.x, 0, t.x, cy);
      cone.addColorStop(0, `rgba(${it.color},0)`); cone.addColorStop(1, `rgba(${it.color},${0.22 * a / it.dim})`);
      ctx.fillStyle = cone;
      ctx.beginPath(); ctx.moveTo(t.x - 30, 0); ctx.lineTo(t.x + 30, 0); ctx.lineTo(t.x + r * 0.7, cy + r * 0.3); ctx.lineTo(t.x - r * 0.7, cy + r * 0.3); ctx.closePath(); ctx.fill();
    },
    sprite(ctx, it, k, now) {
      if (!it.d.ready) return;
      const e = k < it.peak ? k / it.peak : 1;
      const scale = it.from.scale + (it.to.scale - it.from.scale) * k;
      const alpha = k < it.peak ? it.from.alpha + (1 - it.from.alpha) * e : 1 - (k - it.peak) / (1 - it.peak) * (1 - it.to.alpha);
      const w = (it.w ?? it.d.w) * scale, h = (it.h ?? (it.w ? it.w * it.d.h / it.d.w : it.d.h)) * scale;
      ctx.globalAlpha = Math.max(0, Math.min(1, alpha));
      if (it.blend) ctx.globalCompositeOperation = it.blend;
      ctx.translate(it.x, it.y); ctx.rotate(it.from.rot + (it.to.rot - it.from.rot) * k);
      it.d.draw(ctx, -w / 2, -h / 2, w, h, { t: now });
    },
    fly(ctx, it, k, now) {
      const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      const x = it.sx + (it.tx - it.sx) * e, y = it.sy + (it.ty - it.sy) * e - Math.sin(e * Math.PI) * it.arc;
      ctx.globalAlpha = k > 0.85 ? (1 - k) / 0.15 : 1;
      if (it.d?.ready) { const s = it.size * 2; it.d.draw(ctx, x - s / 2, y - s / 2, s, s * it.d.h / it.d.w, { t: now }); return; }
      ctx.shadowColor = '#ffb3d6'; ctx.shadowBlur = 14;
      for (let i = -2; i <= 2; i++) { ctx.fillStyle = i % 2 ? '#f7a8cb' : '#ec6fa6'; ctx.beginPath(); ctx.ellipse(x + i * it.size * 0.32, y, it.size * 0.28, it.size * 0.6, i * 0.35, 0, 6.283); ctx.fill(); }
      ctx.fillStyle = '#ffd36b'; ctx.beginPath(); ctx.arc(x, y + it.size * 0.15, it.size * 0.16, 0, 6.283); ctx.fill();
    },
  };

  function heart(ctx, x, y, s) {
    ctx.beginPath(); ctx.moveTo(x, y + s * 0.3);
    ctx.bezierCurveTo(x, y, x - s / 2, y, x - s / 2, y + s * 0.3);
    ctx.bezierCurveTo(x - s / 2, y + s * 0.6, x, y + s * 0.8, x, y + s);
    ctx.bezierCurveTo(x, y + s * 0.8, x + s / 2, y + s * 0.6, x + s / 2, y + s * 0.3);
    ctx.bezierCurveTo(x + s / 2, y, x, y, x, y + s * 0.3); ctx.fill();
  }
  function star(ctx, x, y, r) {
    ctx.beginPath();
    for (let i = 0; i < 10; i++) { const a = (i / 10) * 6.283 - Math.PI / 2, rr = i % 2 ? r * 0.45 : r; ctx[i ? 'lineTo' : 'moveTo'](x + Math.cos(a) * rr, y + Math.sin(a) * rr); }
    ctx.closePath(); ctx.fill();
  }

  window.Kit = window.Kit || {};
  window.Kit.fx = { emit, emitter, stop, rain, halo, rays, pillar, text, flash, shake, spotlight, sprite, fly, fireworks, preset, beat, update, draw, shakeOffset, PRESETS, get count() { return items.length; } };
})();
