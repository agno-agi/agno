// Sân khấu 3D dựng sẵn cho cảnh "renderer": "3d" (scene3d.js tự nạp file này): đèn quét có tia sáng,
// laser, màn hình video, và hiệu ứng 3D (pháo hoa, confetti, cột sáng, vòng sáng). Mọi thứ tuỳ chọn, khai báo trong scene.json:
//   "stage": {
//     "lights": [{ "at": [-3, 6, -3], "color": "#ff3cac", "sweep": 3, "speed": 0.6, "target": [0, 3], "angle": 14, "intensity": 40 }],
//     "lasers": { "from": [0, 5, -4], "count": 8, "colors": ["#00ffd5", "#ff2bd6"], "spread": 70, "speed": 0.5, "width": 0.035, "always": false },
//     "screens": [{ "at": [0, 3.5, -5], "size": [6, 3.4], "video": "assets/video/loop.mp4" }]   // hoặc "videos": [...], "folder": "video", "image": "..."
//   }
// Bước hành động: { "stage": "party", "duration": 6000 } (đèn mạnh, quét nhanh, bật laser), { "stage": "calm" }, { "stage": "strobe" }
//                 { "fx3d": "fireworks", "at": "stage", "bursts": 4 }, { "fx3d": "confetti", "count": 300 },
//                 { "fx3d": "beam", "at": "person", "color": "#ffd27a" }, { "fx3d": "ring", "at": "person" }

export function createStage({ T, scene, cfg, worldPoint, beat }) {
  const st = cfg.stage || {};
  const now = () => performance.now();
  const color = (c, d) => new T.Color(c || d);
  const live = []; // hiệu ứng đang chạy: { update(dt, t) → false khi xong, dispose() }
  let partyUntil = 0, party = 0, strobeUntil = 0, hidden = false;

  // Vật liệu sáng cộng dồn, mờ dần theo chiều dài (tia đèn, cột sáng)
  function glowMaterial(c, opacity = 0.35, fadePow = 1.6) {
    return new T.ShaderMaterial({
      uniforms: { uColor: { value: color(c, '#ffffff') }, uOpacity: { value: opacity }, uPow: { value: fadePow } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: 'uniform vec3 uColor; uniform float uOpacity; uniform float uPow; varying vec2 vUv; void main(){ gl_FragColor = vec4(uColor, uOpacity * pow(vUv.y, uPow)); }',
      transparent: true, depthWrite: false, blending: T.AdditiveBlending, side: T.DoubleSide,
    });
  }

  // ---------- Đèn quét (moving head): đèn thật chiếu xuống sàn + tia sáng nhìn thấy ----------
  const heads = (st.lights || []).map((l, i) => {
    const at = worldPoint(l.at) || { x: 0, y: 6, z: -3 };
    const base = worldPoint(l.target) || { x: at.x, y: 0, z: at.z + 4 };
    const angle = T.MathUtils.degToRad(l.angle ?? 14);
    const spot = new T.SpotLight(color(l.color, '#ffffff'), l.intensity ?? 40, 0, angle, 0.5, 1.5);
    spot.position.set(at.x, at.y, at.z);
    scene.add(spot, spot.target);
    const geo = new T.ConeGeometry(1, 1, 24, 1, true);
    geo.translate(0, -0.5, 0); // đỉnh nón ở gốc, thân nón chạy xuống dưới
    const beam = new T.Mesh(geo, glowMaterial(l.color, l.beam ?? 0.28));
    beam.position.copy(spot.position);
    scene.add(beam);
    return { l, at, base, angle, spot, beam, phase: i * 1.7, intensity: l.intensity ?? 40 };
  });
  const down = new T.Vector3(0, -1, 0);
  function updateHeads(t) {
    const pulse = beat?.bpm ? 0.7 + 0.3 * beat.pulse(t) : 1;
    const strobe = t < strobeUntil ? (Math.floor(t / 70) % 2) : 1;
    for (const h of heads) {
      const sp = (h.l.speed ?? 0.6) * (1 + party * 1.5), sw = (h.l.sweep ?? 3) * (1 + party * 0.6);
      const k = t / 1000 * sp + h.phase;
      const tx = h.base.x + Math.sin(k) * sw, tz = h.base.z + Math.cos(k * 0.7) * sw * 0.5;
      h.spot.target.position.set(tx, h.base.y || 0, tz);
      h.spot.intensity = h.intensity * (1 + party) * pulse * strobe;
      const dir = new T.Vector3(tx - h.at.x, (h.base.y || 0) - h.at.y, tz - h.at.z);
      const len = dir.length();
      dir.normalize();
      h.beam.quaternion.setFromUnitVectors(down, dir);
      const r = Math.tan(h.angle) * len;
      h.beam.scale.set(r, len, r);
      h.beam.material.uniforms.uOpacity.value = (h.l.beam ?? 0.28) * (0.8 + party * 0.6) * pulse * strobe;
    }
  }

  // ---------- Laser: chùm tia mảnh xoè hình quạt, quay qua lại; bật khi "party" (hoặc luôn bật) ----------
  const L = st.lasers;
  let laser = null;
  if (L) {
    const g = new T.Group();
    const from = worldPoint(L.from) || { x: 0, y: 5, z: -4 };
    g.position.set(from.x, from.y, from.z);
    const n = L.count ?? 8, colors = L.colors || ['#00ffd5', '#ff2bd6'];
    const beams = [];
    for (let i = 0; i < n; i++) {
      const m = new T.Mesh(new T.CylinderGeometry(L.width ?? 0.035, L.width ?? 0.035, 1, 6, 1, true), new T.MeshBasicMaterial({ color: color(colors[i % colors.length]), transparent: true, opacity: 0.9, blending: T.AdditiveBlending, depthWrite: false }));
      m.geometry.translate(0, 0.5, 0);
      m.scale.y = L.length ?? 30;
      const pivot = new T.Group(); pivot.add(m); g.add(pivot);
      beams.push({ pivot, k: n > 1 ? i / (n - 1) - 0.5 : 0 });
    }
    scene.add(g);
    laser = { g, beams };
  }
  function updateLasers(t) {
    if (!laser) return;
    const on = !hidden && (L.always || party > 0.05);
    laser.g.visible = on;
    if (!on) return;
    const spread = T.MathUtils.degToRad(L.spread ?? 70), s = t / 1000 * (L.speed ?? 0.5);
    for (const b of laser.beams) {
      b.pivot.rotation.set(Math.PI / 2 + 0.35 + Math.sin(s * 1.3 + b.k * 3) * 0.25, 0, b.k * spread + Math.sin(s) * 0.4);
      b.pivot.children[0].material.opacity = (L.always ? 0.7 : party) * 0.9;
    }
  }

  // ---------- Màn hình: video lặp / danh sách phát / thư mục / ảnh ----------
  const screens = [];
  for (const s of st.screens || []) {
    const [w, h] = s.size || [6, 3.4];
    const mat = new T.MeshBasicMaterial({ color: 0x111111, toneMapped: false });
    const mesh = new T.Mesh(new T.PlaneGeometry(w, h), mat);
    const at = worldPoint(s.at) || { x: 0, y: 3.5, z: -5 };
    mesh.position.set(at.x, at.y, at.z);
    if (s.rotation) mesh.rotation.set(...s.rotation.map((d) => T.MathUtils.degToRad(d)));
    mesh.visible = !hidden;
    scene.add(mesh);
    const screen = { mesh, v: null };
    screens.push(screen);
    const show = (tex) => { tex.colorSpace = T.SRGBColorSpace; mat.map = tex; mat.color.set(0xffffff); mat.needsUpdate = true; };
    if (s.image) new T.TextureLoader().load(s.image, show);
    const play = (list) => {
      if (!list.length) return;
      const v = Object.assign(document.createElement('video'), { muted: true, playsInline: true, autoplay: true, crossOrigin: 'anonymous', loop: list.length === 1 });
      let i = 0;
      const next = () => { v.src = list[i++ % list.length]; v.play().catch(() => {}); };
      v.addEventListener('ended', next);
      next();
      show(new T.VideoTexture(v));
      screen.v = v;
    };
    if (s.video) play([s.video]);
    else if (s.videos) play(s.videos);
    else if (s.folder) fetch(`/api/theme-files?dir=${encodeURIComponent(s.folder)}`).then((r) => r.json())
      .then(({ files }) => play(files.filter((f) => /\.(mp4|webm)$/i.test(f)).map((f) => `assets/${s.folder}/${f}`))).catch(() => {});
  }

  // ---------- Hiệu ứng 3D ----------
  const rand = (a, b) => a + Math.random() * (b - a);
  const palette = (step) => (step.colors || ['#ff5a5a', '#ffd25a', '#5affb4', '#5ab4ff', '#ff5ae1', '#ffffff']).map((c) => color(c));

  function fireworks(pos, step) {
    const bursts = Math.min(12, step.bursts ?? 4), cols = palette(step);
    for (let b = 0; b < bursts; b++) setTimeout(() => {
      const n = step.particles ?? 160;
      const p = new Float32Array(n * 3), v = new Float32Array(n * 3), c = new Float32Array(n * 3);
      const o = { x: pos.x + rand(-3, 3), y: (pos.y || 0) + rand(5, 8), z: pos.z + rand(-1.5, 1.5) };
      const col = cols[Math.floor(Math.random() * cols.length)];
      for (let i = 0; i < n; i++) {
        const u = rand(-1, 1), th = rand(0, Math.PI * 2), r = Math.sqrt(1 - u * u), sp = rand(3.5, 6);
        p.set([o.x, o.y, o.z], i * 3); v.set([r * Math.cos(th) * sp, u * sp, r * Math.sin(th) * sp], i * 3); c.set([col.r, col.g, col.b], i * 3);
      }
      const geo = new T.BufferGeometry();
      geo.setAttribute('position', new T.BufferAttribute(p, 3)); geo.setAttribute('color', new T.BufferAttribute(c, 3));
      const mat = new T.PointsMaterial({ size: step.size ?? 0.16, vertexColors: true, transparent: true, depthWrite: false, blending: T.AdditiveBlending });
      const pts = new T.Points(geo, mat); scene.add(pts);
      let age = 0; const life = 1.8;
      live.push({
        update(dt) {
          age += dt; const s = dt;
          for (let i = 0; i < n; i++) { v[i * 3 + 1] -= 4 * s; v[i * 3] *= 0.985; v[i * 3 + 2] *= 0.985; p[i * 3] += v[i * 3] * s; p[i * 3 + 1] += v[i * 3 + 1] * s; p[i * 3 + 2] += v[i * 3 + 2] * s; }
          geo.attributes.position.needsUpdate = true;
          mat.opacity = Math.max(0, 1 - age / life);
          return age < life;
        },
        dispose() { scene.remove(pts); geo.dispose(); mat.dispose(); },
      });
    }, b * (step.stagger ?? 350));
  }

  function confetti(step) {
    const n = Math.min(800, step.count ?? 300), cols = palette(step);
    const fl = cfg.floor || { x: [-6, 6], z: [-1, 7] };
    const mesh = new T.InstancedMesh(new T.PlaneGeometry(0.09, 0.14), new T.MeshBasicMaterial({ side: T.DoubleSide, toneMapped: false }), n);
    const parts = [];
    const m = new T.Matrix4(), q = new T.Quaternion(), e = new T.Euler(), one = new T.Vector3(1, 1, 1), pos = new T.Vector3();
    for (let i = 0; i < n; i++) {
      parts.push({ x: rand(fl.x[0] - 1, fl.x[1] + 1), y: rand(6, 12), z: rand(fl.z[0] - 3, fl.z[1]), vy: rand(1.1, 2), ph: rand(0, 6), rx: rand(1, 4), rz: rand(1, 4) });
      mesh.setColorAt(i, cols[i % cols.length]);
    }
    scene.add(mesh);
    let age = 0;
    live.push({
      update(dt) {
        age += dt;
        let alive = false;
        parts.forEach((p, i) => {
          p.y -= p.vy * dt; if (p.y > 0) alive = true;
          pos.set(p.x + Math.sin(age * 2 + p.ph) * 0.3, Math.max(0.01, p.y), p.z);
          q.setFromEuler(e.set(age * p.rx + p.ph, age * 1.5, age * p.rz));
          mesh.setMatrixAt(i, m.compose(pos, q, one));
        });
        mesh.instanceMatrix.needsUpdate = true;
        return alive && age < 14;
      },
      dispose() { scene.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); mesh.dispose(); },
    });
  }

  function beam(pos, step) {
    const h = step.height ?? 14;
    const geo = new T.CylinderGeometry(step.radius ?? 0.55, (step.radius ?? 0.55) * 1.6, h, 32, 1, true);
    geo.translate(0, h / 2, 0);
    // vUv.y = 0 ở chân, 1 ở đỉnh: đảo lại để sáng ở chân, mờ dần lên trên
    const pa = geo.attributes.uv; for (let i = 0; i < pa.count; i++) pa.setY(i, 1 - pa.getY(i));
    const mat = glowMaterial(step.color || '#ffd27a', 0, 1.2);
    const mesh = new T.Mesh(geo, mat); mesh.position.set(pos.x, 0, pos.z); scene.add(mesh);
    let age = 0; const life = (step.duration ?? 2200) / 1000;
    live.push({
      update(dt) { age += dt; const k = age / life; mat.uniforms.uOpacity.value = (step.opacity ?? 0.55) * Math.sin(Math.min(1, k) * Math.PI); mesh.rotation.y += dt; return k < 1; },
      dispose() { scene.remove(mesh); geo.dispose(); mat.dispose(); },
    });
  }

  function ring(pos, step) {
    const mat = new T.MeshBasicMaterial({ color: color(step.color, '#ffd27a'), transparent: true, depthWrite: false, blending: T.AdditiveBlending, side: T.DoubleSide });
    const mesh = new T.Mesh(new T.RingGeometry(0.85, 1, 64), mat);
    mesh.rotation.x = -Math.PI / 2; mesh.position.set(pos.x, 0.03, pos.z); scene.add(mesh);
    let age = 0; const life = (step.duration ?? 1300) / 1000, size = step.size ?? 3.5;
    live.push({
      update(dt) { age += dt; const k = age / life; mesh.scale.setScalar(0.2 + k * size); mat.opacity = Math.max(0, 1 - k); return k < 1; },
      dispose() { scene.remove(mesh); mesh.geometry.dispose(); mat.dispose(); },
    });
  }

  return {
    update(t, dt) {
      const target = t < partyUntil ? 1 : 0;
      party += (target - party) * Math.min(1, dt / 400);
      updateHeads(t); updateLasers(t);
      const s = dt / 1000;
      for (let i = live.length - 1; i >= 0; i--) if (!live[i].update(s, t)) { live[i].dispose(); live.splice(i, 1); }
    },
    command(step) {
      const ms = step.duration ?? 6000;
      if (step.stage === 'party') partyUntil = Math.max(partyUntil, now() + ms);
      else if (step.stage === 'calm') partyUntil = 0;
      else if (step.stage === 'strobe') strobeUntil = now() + (step.duration ?? 1200);
    },
    fx(step, pos) {
      if (live.length > 60) return; // giữ máy nhẹ khi live đông
      if (step.fx3d === 'fireworks') fireworks(pos, step);
      else if (step.fx3d === 'confetti') confetti(step);
      else if (step.fx3d === 'beam') beam(pos, step);
      else if (step.fx3d === 'ring') ring(pos, step);
    },
    setVisible(on) { hidden = !on; for (const h of heads) h.beam.visible = on; for (const s of screens) s.mesh.visible = on; if (laser) laser.g.visible = false; },
  };
}
