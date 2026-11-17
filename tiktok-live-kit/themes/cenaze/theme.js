// Anma teması: özel parçacıklar. Görsel/ses dosyası kullanılmaz; hepsi canvas ile çizilir (telif sorunu yok).
// "mum": yukarı süzülen sıcak alev kıvılcımı, "karanfil": yavaş düşen kırmızı/beyaz yaprak, "nur": yumuşak beyaz ışık.
(function () {
  Kit.fx.preset('mum', { life: [1600, 2600], size: [4, 8], vy: [-70, -30], vx: [-12, 12], sway: 10, alpha: 0.95, shape: 'dot', color: '255,196,110', glow: true, blend: 'lighter', twinkle: true });
  Kit.fx.preset('karanfil', { life: [5000, 8000], size: [9, 15], vy: [60, 120], vx: [-25, 25], sway: 35, spin: [-1.5, 1.5], alpha: 0.95, shape: 'petal', palette: ['190,30,50', '225,225,225', '160,25,45', '245,235,230'] });
  Kit.fx.preset('nur', { life: [2400, 4200], size: [3, 6], vy: [-30, -8], vx: [-10, 10], sway: 14, alpha: 0.9, shape: 'dot', color: '255,248,225', glow: true, blend: 'lighter', twinkle: true });
})();

// 3D mekân: yalnızca temel şekillerle (dosya/lisans yok): arka duvar, iki sütun, iki mum.
(function () {
  let done = false;
  function build() {
    const k = Kit.scene.three;
    if (done || !k || !k.scene || !k.THREE) return false;
    const T = k.THREE, g = new T.Group();
    const stone = new T.MeshStandardMaterial({ color: '#232a34', roughness: 0.95 });
    const wall = new T.Mesh(new T.BoxGeometry(14, 6, 0.4), stone); wall.position.set(0, 3, -6.2); g.add(wall);
    for (const x of [-5, 5]) { const col = new T.Mesh(new T.CylinderGeometry(0.35, 0.4, 6, 16), stone); col.position.set(x, 3, -5.6); g.add(col); }
    const wax = new T.MeshStandardMaterial({ color: '#efe6d2', roughness: 0.8 });
    const flame = new T.MeshBasicMaterial({ color: '#ffcf80' });
    for (const x of [-3.2, 3.2]) {
      const c = new T.Mesh(new T.CylinderGeometry(0.1, 0.12, 0.7, 12), wax); c.position.set(x, 0.35, -2.6); g.add(c);
      const f = new T.Mesh(new T.SphereGeometry(0.09, 10, 8), flame); f.position.set(x, 0.78, -2.6); f.scale.y = 1.6; g.add(f);
    }
    k.scene.add(g); done = true; return true;
  }
  const t = setInterval(() => { if (build()) clearInterval(t); }, 300);
})();
