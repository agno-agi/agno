// Kit.geometry: tính toán phối cảnh và chỗ đứng từ scene.json. Không đụng tới DOM (dùng được trong test).
//
// scene.json (toạ độ theo khung 1080x1920 của ảnh nền):
//   horizonY            đường chân trời (nơi ván sàn, thảm tụ lại)
//   person              { refY, refHeight, exponent }  người cao refHeight px khi đứng ở y = refY;
//                       càng gần càng to theo lũy thừa `exponent` (1 = đúng phối cảnh, nhỏ hơn = đều cỡ, chứa đông hơn)
//   floor               { top, bottom, left, right }   vùng sàn đặt đám đông
//   aisle               { x, half: [[y1, w1], [y2, w2]], lane }  lối đi giữa (nửa bề rộng theo độ sâu), làn đi bộ
//   spacing             { col, row }   khoảng cách ngang / dọc tính theo chiều cao người (mặc định 0.74 / 0.36)
//   obstacles           [{ x0, x1, y0, y1 }]  vùng không đặt người (chân cột, bàn...)
//   seats               [[x, y], ...]  ghế danh dự theo thứ tự ưu tiên

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

  /** Chiều cao người (tư thế nghỉ) tại độ sâu y. */
  function personH(s, y) {
    const { refY, refHeight, exponent } = s.person;
    const ratio = Math.max(0.2, (y - s.horizonY) / Math.max(1, refY - s.horizonY));
    return refHeight * Math.pow(ratio, exponent);
  }

  /** Nửa bề rộng lối đi tại y (nội suy tuyến tính giữa hai mốc đo). */
  function aisleHalf(s, y) {
    if (!s.aisle) return 0;
    const [[y1, w1], [y2, w2]] = s.aisle.half;
    if (y2 === y1) return w1;
    return Math.max(0, w1 + ((w2 - w1) * (y - y1)) / (y2 - y1));
  }

  const blocked = (s, x, y, pad) => s.obstacles.some((o) => x > o.x0 - pad && x < o.x1 + pad && y > o.y0 && y < o.y1);

  /** Chỗ đứng trên sàn với độ thưa `density` (1 = dày nhất, 1.6 = thưa). Thứ tự: gần nơi thờ / sân khấu trước, sát lối giữa trước. */
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
  /** Bộ chỗ đứng theo số người: phòng vắng thì thưa (nhìn vẫn kín), đông thì dày. */
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
