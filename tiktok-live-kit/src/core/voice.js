// Câu giọng đọc của theme: chọn mẫu câu theo sự kiện, điền {ten}, {qua}, {lan}, {xu}, {loi}...
// {loi} = bình luận gần nhất của chính người đó (lời nguyện, lời chúc), không có thì lấy câu dự phòng.

const lowerFirst = (s) => (s ? s[0].toLocaleLowerCase('tr') + s.slice(1) : s);
const pick = (list) => (Array.isArray(list) && list.length ? list[Math.floor(Math.random() * list.length)] : '');

/** Tên đọc cho dễ nghe: bỏ ký tự lạ, gạch dưới, chấm, @. */
export const spokenName = (s) => String(s || '').replace(/[_@.]+/g, ' ').replace(/[^\p{L}\p{N}\s]/gu, '').replace(/\s+/g, ' ').trim().slice(0, 40) || 'dostumuz';

// Canlıda sesli okunan sohbet: link, küfür, yalnızca emoji/rakam olan mesajlar atlanır
import { hasProfanity } from './profanity.js';
export function readableChat(text, extraBlock = []) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  if (t.length < 2 || t.length > 90) return '';
  if (/https?:|www\.|\.(com|net|org|me|tr|vn)\b|@\w/i.test(t)) return '';
  if (!/\p{L}{2,}/u.test(t)) return '';
  if (hasProfanity(t, extraBlock)) return '';
  return t.replace(/[^\p{L}\p{N}\s.,!?'"-]/gu, '').trim();
}

export function createVoice() {
  const lastWords = new Map(); // id -> { text, at }
  const lastAt = new Map(); // loại câu -> lần đọc gần nhất (giãn cách theo voice.cooldown)

  function remember(userId, text) {
    const t = String(text || '').trim();
    if (t.length >= 6) lastWords.set(userId, { text: t.slice(0, 120), at: Date.now() });
    if (lastWords.size > 2000) lastWords.delete(lastWords.keys().next().value);
  }

  /** Câu đọc cho một sự kiện, hoặc '' nếu theme không có mẫu cho sự kiện đó. */
  function line(voiceCfg = {}, ev) {
    if (!voiceCfg.enabled) return '';
    const kind = ev.kind === 'gift' ? (ev.big && voiceCfg.bigGift?.length ? 'bigGift' : 'gift')
      : ev.kind === 'command' && ev.draw ? (ev.draw.again && voiceCfg.drawAgain?.length ? 'drawAgain' : 'draw')
      : ev.kind === 'command' && voiceCfg[`command:${ev.action}`] ? `command:${ev.action}` // câu riêng cho từng lệnh chat
      : ev.kind;
    if (kind === 'gift' && (ev.total || 0) < (voiceCfg.giftMinCoins ?? 1)) return '';
    let chat = '';
    if (kind === 'chat') {
      if (ev.command) return ''; // lệnh chơi: đọc bằng câu của lệnh đó
      chat = readableChat(ev.text, voiceCfg.blockWords);
      if (!chat) return '';
    }
    const cd = voiceCfg.cooldown?.[kind];
    if (cd && Date.now() - (lastAt.get(kind) || 0) < cd) return '';
    const template = pick(voiceCfg[kind]);
    if (!template) return '';
    if (cd) lastAt.set(kind, Date.now());
    const u = ev.user || {};
    const said = lastWords.get(u.id);
    const loi = said && Date.now() - said.at < 120000 ? said.text : pick(voiceCfg.fallbackWords);
    return fill(template, {
      ten: spokenName(u.name),
      qua: ev.gift?.name || ev.label || 'hediye',
      lan: ev.count > 1 ? `, ${ev.count} adet` : '',
      xu: ev.total ?? '',
      hanh_dong: lowerFirst(ev.label || ''),
      danh_hieu: ev.title || u.title || '',
      muc_tieu: ev.label || '',
      gia_tri: ev.value ?? '',
      loi,
      chat,
      // bốc thăm: mọi trường của lá thăm thành biến ({so}, {loai}, {tho}...), mảng nối bằng dấu phẩy
      ...Object.fromEntries(Object.entries(ev.draw || {}).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : v])),
    });
  }

  return { remember, line };
}

/** Điền {khoa}; khoá không có thì bỏ trống. Gọn dấu câu thừa sau khi điền. */
export function fill(template, vars) {
  return String(template)
    .replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? '').toString())
    .replace(/\s+([.,!?])/g, '$1')
    .replace(/([.,!?]){2,}/g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();
}
