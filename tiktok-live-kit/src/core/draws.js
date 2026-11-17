// Bốc thăm cho lệnh chat (xin xăm, rút bài, bói...). Theme khai báo trong theme.json:
//   "draws": { "loi-chuc": { "perDay": true, "items": [ { "title": "...", "text": "..." } ] } }
// rồi trỏ lệnh chat tới: "chatCommands": [{ "keywords": ["rút thăm"], "action": "draw", "draw": "loi-chuc" }].
// perDay (mặc định): mỗi người mỗi ngày một quẻ cố định, hỏi lại vẫn ra quẻ cũ (kèm cờ again).

const hash = (s) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };

export function createDraws() {
  const given = new Map(); // khoá người + ngày + bộ thăm → đã bốc

  function pick(draws, name, userId, now = new Date()) {
    const d = draws?.[name];
    const items = Array.isArray(d?.items) ? d.items : [];
    if (!items.length) return null;
    const day = now.toLocaleDateString('sv-SE');
    const key = `${userId}|${day}|${name}`;
    const i = d.perDay === false ? Math.floor(Math.random() * items.length) : hash(key) % items.length;
    const again = d.perDay !== false && given.has(key);
    given.set(key, true);
    if (given.size > 5000) given.delete(given.keys().next().value);
    return { name, n: i + 1, again, ...items[i] };
  }

  return { pick };
}
