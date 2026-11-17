// Kit.geometry: scene.json'dan perspektif ve duruş yeri hesapları. DOM'a dokunmaz (testte kullanılabilir).
//
// scene.json (arka plan görselinin 1080x1920 çerçevesine göre koordinatlar):
//   horizonY            ufuk çizgisi (zemin tahtalarının, halının birleştiği yer)
//   person              { refY, refHeight, exponent }  kişi y = refY'de dururken refHeight piksel boyundadır;
//                       yaklaştıkça `exponent` üssüne göre büyür (1 = tam perspektif, küçük = boylar eşitlenir, daha kalabalık sığar)
//   floor               { top, bottom, left, right }   kalabalığın yerleştirileceği zemin alanı
//   aisle               { x, half: [[y1, w1], [y2, w2]], lane }  orta koridor (derinliğe göre yarım genişlik), yürüme şeridi
//   spacing             { col, row }   kişi boyuna göre yatay / dikey aralık (varsayılan 0.74 / 0.36)
//   obstacles           [{ x0, x1, y0, y1 }]  kimsenin durmayacağı alanlar (sütun dibi, masa...)
//   seats               [[x, y], ...]  öncelik sırasına göre onur koltukları (sıradaki i. kişi seats[i]'ye oturur)

(function (root) {
  const DEFAULTS = {
    horizonY: 600,
    person: { refY: 1000, refHeight: 60, exponent: 0.5 },
    floor: { top: 1050, bottom: 1640, left: 30, right: 1050 },
    aisle: { x: 540, half: [[1000, 30], [1900, 90]], lane: 80 },
    spacing: { col: 0.74, row: 0.36 },
    obstacles: [],
    seats: [],
  };

  function normalize(scene = {}) {
    const s = { ...DEFAULTS, ...scene };
    s.person = { ...DEFAULTS.person, ...(scene.person || {}) };
    s.floor = { ...DEFAULTS.floor, ...(scene.floor || {}) };
    s.aisle = scene.aisle === null ? null : { ...DEFAULTS.aisle, ...(scene.aisle || {}) };
    s.spacing = { ...DEFAULTS.spacing, ...(scene.spacing || {}) };
    s.obstacles = scene.obstacles || [];
    s.seats = (scene.seats || []).map((p) => (Array.isArray(p) ? { x: p[0], y: p[1] } : p));
    return s;
  }

  /** Derinlik y'de kişinin boyu (dinlenme pozunda). */
  function personH(s, y) {
    const { refY, refHeight, exponent } = s.person;
    const ratio = Math.max(0.2, (y - s.horizonY) / Math.max(1, refY - s.horizonY));
    return refHeight * Math.pow(ratio, exponent);
  }

  /** y'de koridorun yarım genişliği (iki ölçüm noktası arasında doğrusal ara değer). */
  function aisleHalf(s, y) {
    if (!s.aisle) return 0;
    const [[y1, w1], [y2, w2]] = s.aisle.half;
    if (y2 === y1) return w1;
    return Math.max(0, w1 + ((w2 - w1) * (y - y1)) / (y2 - y1));
  }

  const blocked = (s, x, y, pad) => s.obstacles.some((o) => x > o.x0 - pad && x < o.x1 + pad && y > o.y0 && y < o.y1);

  /** `density` seyrekliğiyle zemindeki duruş yerleri (1 = en sık, 1.6 = seyrek). Sıra: önce ön/sahne yakını, önce koridora yakın olanlar. */
  function buildSlots(scene, density = 1) {
    const s = scene.horizonY !== undefined && scene.person?.refY ? scene : normalize(scene);
    const list = [];
    const ax = s.aisle ? s.aisle.x : (s.floor.left + s.floor.right) / 2;
    for (let y = s.floor.top; y <= s.floor.bottom; y += personH(s, y) * s.spacing.row * density) {
      const h = personH(s, y), gap = h * s.spacing.col * density;
      const edge = s.aisle ? aisleHalf(s, y) + gap * 0.6 : gap / 2;
      const push = (x) => { if (!blocked(s, x, y, gap * 0.3)) list.push({ x: Math.round(x), y: Math.round(y) }); };
      for (let x = ax - edge; x > s.floor.left + gap * 0.3; x -= gap) push(x);
      for (let x = ax + edge; x < s.floor.right - gap * 0.3; x += gap) push(x);
    }
    return list.sort((a, b) => (a.y - b.y) || (Math.abs(a.x - ax) - Math.abs(b.x - ax)));
  }

  const LEVELS = [1.7, 1.35, 1.0];
  /** Kişi sayısına göre duruş yeri kümesi: oda boşken seyrek (yine de dolu görünür), kalabalıkken sık. */
  function layoutFor(scene, count) {
    const s = normalize(scene);
    for (const d of LEVELS) {
      const slots = buildSlots(s, d);
      if (slots.length >= count * 1.15 || d === LEVELS[LEVELS.length - 1]) return { density: d, slots };
    }
    return { density: 1, slots: buildSlots(s, 1) };
  }

  const api = { DEFAULTS, normalize, personH, aisleHalf, buildSlots, layoutFor, LEVELS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.Kit = root.Kit || {};
  root.Kit.geometry = api;
})(typeof window !== 'undefined' ? window : globalThis);
