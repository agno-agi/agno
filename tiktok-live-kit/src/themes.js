// Nạp theme từ thư mục themes/<id>/: theme.json (nội dung, luật, giọng đọc...) + scene.json (bố cục cảnh).

import fs from 'node:fs';
import path from 'node:path';

const readJson = (f, fallback = null) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return fallback; } };

/** Theme trong một hoặc nhiều thư mục (thư mục đầu ưu tiên khi trùng tên). Mỗi theme kèm `dir` chứa nó. */
export function listThemes(dirs) {
  const seen = new Map();
  for (const dir of [].concat(dirs)) {
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { continue; }
    for (const d of entries) {
      if (!d.isDirectory() || d.name.startsWith('_') || d.name.startsWith('.') || seen.has(d.name)) continue;
      const t = readJson(path.join(dir, d.name, 'theme.json'));
      if (t) seen.set(d.name, { id: d.name, name: t.name || d.name, description: t.description || '', dir: path.join(dir, d.name) });
    }
  }
  return [...seen.values()];
}

// Cài đặt kit thêm cho mọi theme (theme khai báo cùng id thì dùng bản của theme)
const STANDARD_SETTINGS = [
  { id: 'voiceEnabled', label: 'Sesli okuma (isim/dua)', type: 'toggle', default: true },
  { id: 'voiceVolume', label: 'Ses okuma seviyesi', type: 'range', min: 0, max: 100, default: 90 },
  { id: 'musicVolume', label: 'Fon müziği seviyesi (assets/music)', type: 'range', min: 0, max: 100, default: 30 },
  { id: 'sfxVolume', label: 'Efekt sesi seviyesi (assets/sfx)', type: 'range', min: 0, max: 100, default: 60 },
  { id: 'ambientFx', label: 'Ortam efektleri (duman, parçacık, ışık)', type: 'toggle', default: true },
  { id: 'cameraFx', label: 'Büyük hediye verene kamera yakınlaşması', type: 'toggle', default: true },
  { id: 'chroma', label: 'OBS için yeşil arka plan (chroma key)', type: 'toggle', default: false },
  { id: 'periodicEnabled', label: 'Sohbet sessizken periyodik içerik', type: 'toggle', default: true },
];

export function loadTheme(dirs, id) {
  const all = listThemes(dirs);
  const found = all.find((t) => t.id === id) || all[0];
  if (!found) throw new Error(`Hiç tema bulunamadı: ${[].concat(dirs).join(', ')}`);
  if (found.id !== id) console.warn(`[tema] "${id}" bulunamadı, "${found.id}" kullanılıyor`);
  const pick = found.id, dir = found.dir;
  const t = readJson(path.join(dir, 'theme.json'), {});
  const own = Array.isArray(t.settings) ? t.settings : [];
  return {
    id: pick,
    dir,
    name: t.name || pick,
    width: t.width || 1080,
    height: t.height || 1920,
    actions: Array.isArray(t.actions) && t.actions.length ? t.actions : [{ id: 'default', label: 'Varsayılan' }],
    titles: t.titles || [],
    goals: t.goals || [],
    rules: t.rules || {},
    text: t.text || {},
    settings: [...own, ...STANDARD_SETTINGS.filter((s) => !own.some((o) => o.id === s.id))],
    voice: t.voice || {},
    periodic: t.periodic || {},
    prompts: t.prompts || {},
    prompts: t.prompts || {},
    draws: t.draws || {},
    // phần chỉ overlay dùng, server chuyển nguyên
    characters: t.characters || [],
    animations: t.animations || {},
    npcs: t.npcs || [],
    hud: t.hud || {},
    colors: t.colors || {},
    sounds: t.sounds || {},
    bigGift: t.bigGift || {},
    reactions: t.reactions || {},
    scene: readJson(path.join(dir, 'scene.json'), {}),
  };
}

/** Giá trị cài đặt của theme: mặc định trong theme.json, ghi đè bằng giá trị đã lưu (chỉ nhận khoá có khai báo). */
export function settingValues(theme, saved = {}) {
  const out = {};
  for (const f of theme.settings) {
    let v = saved[f.id] ?? f.default;
    if (f.type === 'range') v = Math.min(f.max ?? 100, Math.max(f.min ?? 0, Number(v) || 0));
    else if (f.type === 'toggle') v = Boolean(v);
    else if (f.type === 'select') v = (f.options || []).some((o) => o.value === v) ? v : f.default;
    else v = String(v ?? '').slice(0, 500);
    out[f.id] = v;
  }
  return out;
}
