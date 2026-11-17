// Anma teması: özel parçacıklar. Görsel/ses dosyası kullanılmaz; hepsi canvas ile çizilir (telif sorunu yok).
// "mum": yukarı süzülen sıcak alev kıvılcımı, "karanfil": yavaş düşen kırmızı/beyaz yaprak, "nur": yumuşak beyaz ışık.
(function () {
  Kit.fx.preset('mum', { life: [1600, 2600], size: [4, 8], vy: [-70, -30], vx: [-12, 12], sway: 10, alpha: 0.95, shape: 'dot', color: '255,196,110', glow: true, blend: 'lighter', twinkle: true });
  Kit.fx.preset('karanfil', { life: [5000, 8000], size: [9, 15], vy: [60, 120], vx: [-25, 25], sway: 35, spin: [-1.5, 1.5], alpha: 0.95, shape: 'petal', palette: ['190,30,50', '225,225,225', '160,25,45', '245,235,230'] });
  Kit.fx.preset('nur', { life: [2400, 4200], size: [3, 6], vy: [-30, -8], vx: [-10, 10], sway: 14, alpha: 0.9, shape: 'dot', color: '255,248,225', glow: true, blend: 'lighter', twinkle: true });
})();

// 3D mekân: yalnızca temel şekillerle (dosya / lisans yok): cami avlusu havası.
// Taş döşeli avlu, kemerli revak, arkada kubbe ve minare siluetleri, selvi ağaçları, yıldızlı gece, iki mum
// ve ön tarafta musalla taşı. Musalla taşındaki örtülü cenaze (SHOW_BIER) ailenin tercihine göre kapatılabilir.
(function () {
  const SHOW_BIER = true;
  let done = false;
  function tileTexture(T) {
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const x = c.getContext('2d');
    x.fillStyle = '#1b2029'; x.fillRect(0, 0, 256, 256);
    for (let r = 0; r < 4; r++) for (let q = 0; q < 4; q++) {
      const l = 28 + ((r * 7 + q * 13) % 5) * 2;
      x.fillStyle = `hsl(215,12%,${l}%)`; x.fillRect(q * 64 + 2, r * 64 + 2, 60, 60);
    }
    const t = new T.CanvasTexture(c); t.wrapS = t.wrapT = T.RepeatWrapping; t.repeat.set(7, 9); t.colorSpace = T.SRGBColorSpace;
    return t;
  }
  function build() {
    const k = Kit.scene.three;
    if (done || !k || !k.scene || !k.THREE) return false;
    const T = k.THREE, g = new T.Group();
    const M = (c, r = 0.95) => new T.MeshStandardMaterial({ color: c, roughness: r });
    const put = (mesh, x, y, z) => { mesh.position.set(x, y, z); g.add(mesh); return mesh; };

    // avlu zemini (taş döşeme)
    const ground = put(new T.Mesh(new T.PlaneGeometry(14, 18), new T.MeshStandardMaterial({ map: tileTexture(T), roughness: 0.9 })), 0, 0.004, 1.5);
    ground.rotation.x = -Math.PI / 2;

    // arkada kemerli revak: 7 sütun, 6 kemer, üstte çatı
    const stone = M('#2a313c'), dim = M('#1a1f27');
    for (let i = -3; i <= 3; i++) put(new T.Mesh(new T.CylinderGeometry(0.22, 0.26, 3.2, 14), stone), i * 2, 1.6, -7);
    for (let i = -3; i < 3; i++) { const a = put(new T.Mesh(new T.TorusGeometry(1, 0.13, 8, 20, Math.PI), stone), i * 2 + 1, 3.2, -7); a.scale.set(1, 0.9, 1); }
    put(new T.Mesh(new T.BoxGeometry(14.6, 0.5, 1.4), dim), 0, 4.55, -7);
    put(new T.Mesh(new T.BoxGeometry(14.6, 5, 0.3), M('#12161c')), 0, 2.5, -7.9);

    // kubbe ve minare silueti (uzakta, koyu)
    const dome = put(new T.Mesh(new T.SphereGeometry(2.6, 24, 12, 0, 6.283, 0, Math.PI / 2), M('#171c24')), -4.5, 4.6, -11);
    put(new T.Mesh(new T.CylinderGeometry(2.6, 2.6, 1.2, 24), M('#171c24')), -4.5, 4.0, -11);
    put(new T.Mesh(new T.CylinderGeometry(0.28, 0.36, 12, 12), M('#171c24')), 5.5, 6, -10.5);
    put(new T.Mesh(new T.ConeGeometry(0.42, 1.8, 12), M('#171c24')), 5.5, 12.9, -10.5);
    put(new T.Mesh(new T.CylinderGeometry(0.5, 0.5, 0.22, 12), M('#171c24')), 5.5, 9.4, -10.5);

    // selvi ağaçları
    for (const [x, z, h] of [[-6.2, -3.5, 5], [6.2, -3.5, 5.5], [-6.6, 2, 4.2], [6.6, 2.5, 4.6]]) {
      put(new T.Mesh(new T.ConeGeometry(0.55, h, 10), M('#0f1c16')), x, h / 2, z);
    }

    // yıldızlı gece
    const pts = []; for (let i = 0; i < 220; i++) pts.push((Math.random() - 0.5) * 60, 8 + Math.random() * 14, -14 - Math.random() * 6);
    const sg = new T.BufferGeometry(); sg.setAttribute('position', new T.Float32BufferAttribute(pts, 3));
    g.add(new T.Points(sg, new T.PointsMaterial({ color: '#cfd8ff', size: 0.07, sizeAttenuation: true })));

    // musalla taşı + örtülü cenaze (saflar buraya doğru döner)
    if (SHOW_BIER) {
      put(new T.Mesh(new T.BoxGeometry(2.6, 0.28, 1.5), M('#3a424f', 0.8)), 0, 0.14, -4.2);
      put(new T.Mesh(new T.BoxGeometry(2.0, 0.38, 0.72), M('#1d3a2c', 0.9)), 0, 0.47, -4.2);   // koyu yeşil örtü
      put(new T.Mesh(new T.BoxGeometry(2.04, 0.04, 0.76), M('#d8cfa8', 0.8)), 0, 0.68, -4.2);  // örtü şeridi
    }

    // siyah araçlar (arkada iki yanda) ve çelenkler
    const paint = M('#07090c', 0.35), glass = M('#1a222c', 0.2);
    for (const [x, z, ry] of [[-8.2, -5.2, 0.35], [8.2, -5.2, -0.35]]) {
      const car = new T.Group(); car.position.set(x, 0, z); car.rotation.y = ry; g.add(car);
      const b = new T.Mesh(new T.BoxGeometry(4.4, 0.8, 1.9), paint); b.position.y = 0.7; car.add(b);
      const c = new T.Mesh(new T.BoxGeometry(2.2, 0.7, 1.7), glass); c.position.set(-0.2, 1.4, 0); car.add(c);
      for (const wx of [-1.4, 1.4]) for (const wz of [-0.95, 0.95]) { const w = new T.Mesh(new T.CylinderGeometry(0.38, 0.38, 0.3, 14), M('#0b0c0e')); w.rotation.x = Math.PI / 2; w.position.set(wx, 0.38, wz); car.add(w); }
    }
    for (const x of [-2.2, 2.2]) {
      const w = put(new T.Mesh(new T.TorusGeometry(0.42, 0.12, 10, 24), M('#1f3d2a', 0.95)), x, 0.62, -5.1);
      for (let i = 0; i < 9; i++) { const a = (i / 9) * 6.283; const f = new T.Mesh(new T.SphereGeometry(0.07, 8, 6), M(i % 2 ? '#b11d2a' : '#e8e8e0')); f.position.set(x + Math.cos(a) * 0.42, 0.62 + Math.sin(a) * 0.42, -5.1); g.add(f); }
      put(new T.Mesh(new T.CylinderGeometry(0.03, 0.03, 0.62, 6), M('#2a2118')), x, 0.3, -5.15);
    }

    // mumlar
    const wax = M('#efe6d2', 0.8), flame = new T.MeshBasicMaterial({ color: '#ffcf80' });
    for (const x of [-3.2, 3.2]) {
      put(new T.Mesh(new T.CylinderGeometry(0.1, 0.12, 0.7, 12), wax), x, 0.35, -2.6);
      const f = put(new T.Mesh(new T.SphereGeometry(0.09, 10, 8), flame), x, 0.78, -2.6); f.scale.y = 1.6;
    }
    k.scene.add(g); done = true; return true;
  }
  const t = setInterval(() => { if (build()) clearInterval(t); }, 300);
})();
