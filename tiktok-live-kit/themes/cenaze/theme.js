// Anma teması: özel parçacıklar. Görsel/ses dosyası kullanılmaz; hepsi canvas ile çizilir (telif sorunu yok).
// "mum": yukarı süzülen sıcak alev kıvılcımı, "karanfil": yavaş düşen kırmızı/beyaz yaprak, "nur": yumuşak beyaz ışık.
(function () {
  Kit.fx.preset('mum', { life: [1600, 2600], size: [4, 8], vy: [-70, -30], vx: [-12, 12], sway: 10, alpha: 0.95, shape: 'dot', color: '255,196,110', glow: true, blend: 'lighter', twinkle: true });
  Kit.fx.preset('karanfil', { life: [5000, 8000], size: [9, 15], vy: [60, 120], vx: [-25, 25], sway: 35, spin: [-1.5, 1.5], alpha: 0.95, shape: 'petal', palette: ['190,30,50', '225,225,225', '160,25,45', '245,235,230'] });
  Kit.fx.preset('nur', { life: [2400, 4200], size: [3, 6], vy: [-30, -8], vx: [-10, 10], sway: 14, alpha: 0.9, shape: 'dot', color: '255,248,225', glow: true, blend: 'lighter', twinkle: true });
})();

// 3D alay sahnesi: yalnızca temel şekillerle (dosya / lisans yok). Taş döşeli yol kayar (alay yürüyormuş gibi),
// iki yanda selvi ağaçları aynı hızla kayar, ortada omuzlarda taşınan örtülü tabut ve üstünde isim levhası (fotoğraf yok).
// SHOW_COFFIN = false yapılırsa tabut gizlenir. SPEED: yolun kayma hızı (metre/sn).
(function () {
  const SHOW_COFFIN = true, SPEED = 1.4, NAME = 'SÜLEYMAN ÇAKIR';
  let world = null;
  function tileTexture(T) {
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const x = c.getContext('2d');
    x.fillStyle = '#1b2029'; x.fillRect(0, 0, 256, 256);
    for (let r = 0; r < 4; r++) for (let q = 0; q < 4; q++) { x.fillStyle = `hsl(215,12%,${28 + ((r * 7 + q * 13) % 5) * 2}%)`; x.fillRect(q * 64 + 2, r * 64 + 2, 60, 60); }
    const t = new T.CanvasTexture(c); t.wrapS = t.wrapT = T.RepeatWrapping; t.repeat.set(4, 12); t.colorSpace = T.SRGBColorSpace;
    return t;
  }
  function plaqueTexture(T) {
    const c = document.createElement('canvas'); c.width = 512; c.height = 160;
    const x = c.getContext('2d');
    x.fillStyle = '#1a1710'; x.fillRect(0, 0, 512, 160);
    x.strokeStyle = '#d8cfa8'; x.lineWidth = 8; x.strokeRect(8, 8, 496, 144);
    x.fillStyle = '#efe6c8'; x.font = '700 54px system-ui, sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.fillText(NAME, 256, 80);
    const t = new T.CanvasTexture(c); t.colorSpace = T.SRGBColorSpace; return t;
  }
  function build() {
    const k = Kit.scene.three;
    if (world || !k || !k.scene || !k.THREE) return false;
    const T = k.THREE, g = new T.Group(), M = (c, r = 0.95) => new T.MeshStandardMaterial({ color: c, roughness: r });
    const put = (mesh, x, y, z) => { mesh.position.set(x, y, z); g.add(mesh); return mesh; };

    const tex = tileTexture(T);
    const ground = put(new T.Mesh(new T.PlaneGeometry(9, 40), new T.MeshStandardMaterial({ map: tex, roughness: 0.9 })), 0, 0.004, -4);
    ground.rotation.x = -Math.PI / 2;
    // kaldırım şeritleri
    for (const x of [-5.2, 5.2]) put(new T.Mesh(new T.BoxGeometry(2.4, 0.18, 40), M('#222831')), x, 0.09, -4);

    // kayan selvi ağaçları (iki yan, 8 sıra)
    const trees = [];
    for (let i = 0; i < 8; i++) for (const sx of [-1, 1]) {
      const h = 3.6 + ((i * 5 + (sx > 0 ? 2 : 0)) % 4) * 0.5;
      const tr = put(new T.Mesh(new T.ConeGeometry(0.5, h, 10), M('#10201a')), sx * 4.8, h / 2, 12 - i * 3.6); trees.push(tr);
    }
    // uzakta kubbe ve minare (sabit)
    put(new T.Mesh(new T.SphereGeometry(2.6, 24, 12, 0, 6.283, 0, Math.PI / 2), M('#171c24')), -6, 4.6, -16);
    put(new T.Mesh(new T.CylinderGeometry(2.6, 2.6, 1.2, 24), M('#171c24')), -6, 4.0, -16);
    put(new T.Mesh(new T.CylinderGeometry(0.28, 0.36, 12, 12), M('#171c24')), 6.5, 6, -15);
    put(new T.Mesh(new T.ConeGeometry(0.42, 1.8, 12), M('#171c24')), 6.5, 12.9, -15);

    // yıldızlı gece
    const pts = []; for (let i = 0; i < 220; i++) pts.push((Math.random() - 0.5) * 60, 8 + Math.random() * 14, -20 - Math.random() * 6);
    const sg = new T.BufferGeometry(); sg.setAttribute('position', new T.Float32BufferAttribute(pts, 3));
    g.add(new T.Points(sg, new T.PointsMaterial({ color: '#cfd8ff', size: 0.07, sizeAttenuation: true })));

    // omuzlarda taşınan örtülü tabut + isim levhası (npc'ler köşelerde durur: scene.json / theme.json "npcs")
    if (SHOW_COFFIN) {
      const cof = new T.Group(); cof.position.set(0, 1.28, -3.4); g.add(cof);
      const box = (w, h, d, c, y = 0) => { const m = new T.Mesh(new T.BoxGeometry(w, h, d), M(c, 0.85)); m.position.y = y; cof.add(m); return m; };
      box(0.9, 0.5, 2.2, '#1d3a2c');            // koyu yeşil örtü
      box(0.94, 0.06, 2.24, '#e0d6a8', 0.1);    // örtü şeritleri
      box(0.94, 0.06, 2.24, '#e0d6a8', -0.1);
      const plate = new T.Mesh(new T.PlaneGeometry(1.0, 0.31), new T.MeshBasicMaterial({ map: plaqueTexture(T) }));
      plate.position.set(0, 0.55, 1.14); plate.rotation.x = -0.35; cof.add(plate);
    }
    k.scene.add(g); world = { tex, trees }; return true;
  }
  let last = performance.now();
  Kit.on('frame', (t) => {
    if (!world) return;
    const dt = Math.min(60, t - last) / 1000; last = t;
    world.tex.offset.y += (SPEED * dt) / (40 / 12);          // yol kayar
    for (const tr of world.trees) { tr.position.z += SPEED * dt; if (tr.position.z > 14) tr.position.z -= 28.8; }
  });
  const tm = setInterval(() => { if (build()) clearInterval(tm); }, 300);
})();
