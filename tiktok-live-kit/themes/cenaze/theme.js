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
  let NAME = 'SÜLEYMAN ÇAKIR'; // levhadaki yazı theme.json > hud.title.text'ten gelir (tek yerden değişir)
  const SHOW_COFFIN = true, SPEED = 1.4;
  Kit.on('start', (th) => { if (th?.hud?.title?.text) NAME = String(th.hud.title.text).toUpperCase(); });
  let world = null;
  function tileTexture(T) {
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const x = c.getContext('2d');
    x.fillStyle = '#9d9684'; x.fillRect(0, 0, 256, 256);
    for (let r = 0; r < 4; r++) for (let q = 0; q < 4; q++) { x.fillStyle = `hsl(40,14%,${66 + ((r * 7 + q * 13) % 5) * 2}%)`; x.fillRect(q * 64 + 2, r * 64 + 2, 60, 60); }
    const t = new T.CanvasTexture(c); t.wrapS = t.wrapT = T.RepeatWrapping; t.repeat.set(4, 12); t.colorSpace = T.SRGBColorSpace;
    return t;
  }
  // Levha: solda çerçeve, sağda ad. Çerçevede varsayılan olarak yüzsüz siluet (özgün çizim) görünür.
  // İsteğe bağlı: themes/cenaze/assets/portrait.png (veya .jpg) dosyası varsa çerçevede o görünür.
  // Dosyayı yalnızca yayın / kullanım hakkı SİZDE olan bir görselle koyun (kişi ve görsel sahibinden yazılı izin). Repoda hazır görsel yoktur.
  function plaqueTexture(T) {
    const c = document.createElement('canvas'); c.width = 640; c.height = 200;
    const x = c.getContext('2d');
    const t = new T.CanvasTexture(c); t.colorSpace = T.SRGBColorSpace;
    function frame(img) {
      x.fillStyle = '#1a1710'; x.fillRect(0, 0, 640, 200);
      x.strokeStyle = '#d8cfa8'; x.lineWidth = 8; x.strokeRect(8, 8, 624, 184);
      if (img) { // görseli çerçeveye "cover" olarak sığdır
        const r = Math.max(150 / img.width, 152 / img.height), w = img.width * r, h = img.height * r;
        x.save(); x.beginPath(); x.rect(24, 24, 150, 152); x.clip(); x.drawImage(img, 24 + (150 - w) / 2, 24 + (152 - h) / 2, w, h); x.restore();
      } else {
        const grd = x.createLinearGradient(0, 24, 0, 176); grd.addColorStop(0, '#4a4f58'); grd.addColorStop(1, '#22252b');
        x.fillStyle = grd; x.fillRect(24, 24, 150, 152);
        x.fillStyle = '#0c0d10';
        x.beginPath(); x.ellipse(99, 82, 24, 28, 0, 0, 6.283); x.fill();                 // baş
        x.beginPath(); x.ellipse(99, 56, 44, 7, 0, 0, 6.283); x.fill();                   // şapka kenarı
        x.fillRect(79, 36, 40, 22);                                                       // şapka tacı
        x.beginPath(); x.moveTo(26, 176); x.lineTo(40, 124); x.quadraticCurveTo(99, 100, 158, 124); x.lineTo(172, 176); x.closePath(); x.fill(); // omuz / palto
      }
      x.fillStyle = '#efe6c8'; x.font = '700 50px system-ui, sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
      x.fillText(NAME, 410, 100, 430);
      t.needsUpdate = true;
    }
    frame(null);
    for (const f of ['assets/portrait.png', 'assets/portrait.jpg']) {
      const im = new Image(); im.onload = () => frame(im); im.src = f;
    }
    return t;
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
    for (const x of [-5.2, 5.2]) put(new T.Mesh(new T.BoxGeometry(2.4, 0.18, 40), M('#b9b2a2')), x, 0.09, -4);

    // kayan ağaçlar (iki yan): gövde + yuvarlak taç
    const trees = [];
    const leaf = [M('#3f7a3a'), M('#4b8a3f'), M('#356b34')];
    for (let i = 0; i < 8; i++) for (const sx of [-1, 1]) {
      const z = 12 - i * 3.6, th = new T.Group(); th.position.set(sx * 4.9, 0, z);
      const tr = new T.Mesh(new T.CylinderGeometry(0.12, 0.16, 1.5, 8), M('#5a4430')); tr.position.y = 0.75; th.add(tr);
      const cr = new T.Mesh(new T.SphereGeometry(0.95 + ((i + (sx > 0 ? 1 : 0)) % 3) * 0.12, 14, 10), leaf[(i + (sx > 0 ? 1 : 0)) % 3]); cr.position.y = 2.2; th.add(cr);
      g.add(th); trees.push(th);
    }
    // sokağın iki yanında kayan binalar (pencereli)
    const winTex = (() => {
      const c = document.createElement('canvas'); c.width = 128; c.height = 256; const x = c.getContext('2d');
      x.fillStyle = '#d9cfba'; x.fillRect(0, 0, 128, 256);
      for (let r = 0; r < 6; r++) for (let q = 0; q < 3; q++) { x.fillStyle = (r * 3 + q) % 7 === 0 ? '#e8d28a' : '#5f7690'; x.fillRect(14 + q * 38, 14 + r * 40, 26, 28); }
      const t = new T.CanvasTexture(c); t.colorSpace = T.SRGBColorSpace; return t;
    })();
    const blocks = [];
    for (let i = 0; i < 6; i++) for (const sx of [-1, 1]) {
      const h = 7 + ((i * 3 + (sx > 0 ? 1 : 0)) % 4) * 1.6, w = 4.4, d = 5.2;
      const b = new T.Mesh(new T.BoxGeometry(w, h, d), new T.MeshStandardMaterial({ map: winTex, roughness: 0.9 }));
      b.position.set(sx * 7.4, h / 2, 11 - i * 5.4); g.add(b); blocks.push(b);
    }
    // uzakta minare (sabit, açık renk)
    put(new T.Mesh(new T.CylinderGeometry(0.3, 0.4, 14, 12), M('#d8d2c4')), 3.5, 7, -24);
    put(new T.Mesh(new T.ConeGeometry(0.46, 2, 12), M('#8d9aa8')), 3.5, 15, -24);
    put(new T.Mesh(new T.CylinderGeometry(0.55, 0.55, 0.22, 12), M('#c9c2b2')), 3.5, 10.4, -24);

    // omuzlarda taşınan örtülü tabut + isim levhası (npc'ler köşelerde durur: scene.json / theme.json "npcs")
    let cof = null;
    if (SHOW_COFFIN) {
      cof = new T.Group(); cof.position.set(0, 1.28, -3.4); cof.scale.setScalar(1.25); g.add(cof);
      const box = (w, h, d, c, y = 0) => { const m = new T.Mesh(new T.BoxGeometry(w, h, d), M(c, 0.85)); m.position.y = y; cof.add(m); return m; };
      box(0.9, 0.5, 2.2, '#1d3a2c');            // koyu yeşil örtü
      box(0.94, 0.06, 2.24, '#e0d6a8', 0.1);    // örtü şeritleri
      box(0.94, 0.06, 2.24, '#e0d6a8', -0.1);
      const plate = new T.Mesh(new T.PlaneGeometry(1.0, 0.3125), new T.MeshBasicMaterial({ map: plaqueTexture(T) }));
      plate.position.set(0, 0.55, 1.14); plate.rotation.x = -0.35; cof.add(plate);
    }
    k.scene.add(g); world = { tex, trees, blocks, cof }; return true;
  }
  let last = performance.now();
  Kit.on('frame', (t) => {
    if (!world) return;
    const dt = Math.min(60, t - last) / 1000; last = t;
    world.tex.offset.y += (SPEED * dt) / (40 / 12);          // yol kayar
    for (const tr of world.trees) { tr.position.z += SPEED * dt; if (tr.position.z > 14) tr.position.z -= 28.8; }
    if (world.cof) { const w = Math.sin((t / 1000) * 6); world.cof.position.y = 1.28 + Math.abs(w) * 0.035; world.cof.rotation.z = w * 0.012; } // taşıyıcılarla aynı adım
    for (const b of world.blocks) { b.position.z += SPEED * dt; if (b.position.z > 14) b.position.z -= 32.4; }
  });
  const tm = setInterval(() => { if (build()) clearInterval(tm); }, 300);
})();

// "Omuz ver" (1–9 jeton / Gül): gönderen tabutun yanındaki boş noktaya yürür, HOLD süre durur, sonra yerine döner.
// Noktalar scene.json "points" içinde omuz0..omuz5 (en fazla 6 kişi aynı anda; doluysa yalnızca efekt çalışır).
(function () {
  const HOLD = 30000, taken = new Array(6).fill(null);
  Kit.action('omuz', (person) => {
    if (!person || person.npc || taken.includes(person.id)) return;
    const i = taken.indexOf(null);
    if (i < 0) return;
    taken[i] = person.id;
    const P = Kit.scene.P;
    P.walkTo(person, 'omuz' + i); P.pose(person, 'stand'); P.wait(person, HOLD);
    P.walkTo(person, 'home'); P.pose(person, 'idle');
    P.do(person, () => { taken[i] = null; });
  });
  Live.on('reset', () => taken.fill(null));
})();

// "Fotoğrafı taşı" (Parmak Kalp): gönderen tabutun önündeki noktaya yürür, çerçeveyi önünde tutar, sonra yerine döner.
// Çerçevede siluet görünür; assets/portrait.png (veya .jpg) varsa o görünür (bkz. README). Aynı anda tek kişi taşır.
(function () {
  const HOLD = 30000;
  let frame = null, carrier = null, busy = false;
  function portraitTexture(T) {
    const c = document.createElement('canvas'); c.width = 240; c.height = 300;
    const x = c.getContext('2d'), t = new T.CanvasTexture(c); t.colorSpace = T.SRGBColorSpace;
    function draw(img) {
      x.fillStyle = '#1a1710'; x.fillRect(0, 0, 240, 300);
      x.strokeStyle = '#d8cfa8'; x.lineWidth = 12; x.strokeRect(6, 6, 228, 288);
      if (img) { const r = Math.max(204 / img.width, 264 / img.height), w = img.width * r, h = img.height * r; x.save(); x.beginPath(); x.rect(18, 18, 204, 264); x.clip(); x.drawImage(img, 18 + (204 - w) / 2, 18 + (264 - h) / 2, w, h); x.restore(); }
      else {
        const g = x.createLinearGradient(0, 18, 0, 282); g.addColorStop(0, '#4a4f58'); g.addColorStop(1, '#22252b'); x.fillStyle = g; x.fillRect(18, 18, 204, 264);
        x.fillStyle = '#0c0d10';
        x.beginPath(); x.ellipse(120, 120, 34, 40, 0, 0, 6.283); x.fill();
        x.beginPath(); x.ellipse(120, 82, 62, 9, 0, 0, 6.283); x.fill(); x.fillRect(93, 52, 54, 32);
        x.beginPath(); x.moveTo(20, 282); x.lineTo(40, 200); x.quadraticCurveTo(120, 168, 200, 200); x.lineTo(220, 282); x.closePath(); x.fill();
      }
      t.needsUpdate = true;
    }
    draw(null);
    for (const f of ['assets/portrait.png', 'assets/portrait.jpg']) { const im = new Image(); im.onload = () => draw(im); im.src = f; }
    return t;
  }
  function ensureFrame() {
    if (frame) return frame;
    const k = Kit.scene.three; if (!k || !k.scene || !k.THREE) return null;
    const T = k.THREE, g = new T.Group();
    const back = new T.Mesh(new T.BoxGeometry(0.5, 0.62, 0.04), new T.MeshStandardMaterial({ color: '#3a2c18', roughness: 0.6 })); g.add(back);
    const pic = new T.Mesh(new T.PlaneGeometry(0.46, 0.575), new T.MeshBasicMaterial({ map: portraitTexture(T) })); pic.position.z = 0.025; g.add(pic);
    g.visible = false; k.scene.add(g); frame = g; return g;
  }
  Kit.action('foto', (person) => {
    if (!person || person.npc || busy || !ensureFrame()) return;
    busy = true;
    const P = Kit.scene.P;
    P.walkTo(person, 'foto'); P.pose(person, 'stand');
    P.do(person, () => { carrier = person; });
    P.wait(person, HOLD);
    P.walkTo(person, 'home'); P.pose(person, 'idle');
    P.do(person, () => { carrier = null; busy = false; if (frame) frame.visible = false; });
  });
  Kit.on('frame', () => {
    if (!frame) return;
    if (carrier && carrier.obj) { frame.visible = true; frame.position.set(carrier.wx, 1.2, carrier.wz + 0.3); frame.rotation.y = 0; }
  });
  Live.on('reset', () => { carrier = null; busy = false; if (frame) frame.visible = false; });
})();
