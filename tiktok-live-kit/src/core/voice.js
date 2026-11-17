// Temanın seslendirme cümleleri: olaya göre şablon seçer, {ten}, {qua}, {lan}, {xu}, {loi}... alanlarını doldurur.
// {loi} = kişinin kendi son yorumu (dilek, dua); yoksa yedek cümle kullanılır.

const lowerFirst = (s) => (s ? s[0].toLocaleLowerCase('tr') + s.slice(1) : s);
const pick = (list) => (Array.isArray(list) && list.length ? list[Math.floor(Math.random() * list.length)] : '');

/** Kulağa hoş okunsun diye ismi temizler: garip karakter, alt çizgi, nokta, @ atılır. */
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
  const lastAt = new Map(); // cümle türü -> en son okunma zamanı (voice.cooldown ile aralık bırakılır)

  function remember(userId, text) {
    const t = String(text || '').trim();
    if (t.length >= 6) lastWords.set(userId, { text: t.slice(0, 120), at: Date.now() });
    if (lastWords.size > 2000) lastWords.delete(lastWords.keys().next().value);
  }

  /** Bir olay için okunacak cümle; temada o olay için şablon yoksa ''. */
  function line(voiceCfg = {}, ev) {
    if (!voiceCfg.enabled) return '';
    const kind = ev.kind === 'gift' ? (ev.big && voiceCfg.bigGift?.length ? 'bigGift' : 'gift')
      : ev.kind === 'command' && ev.draw ? (ev.draw.again && voiceCfg.drawAgain?.length ? 'drawAgain' : 'draw')
      : ev.kind === 'command' && voiceCfg[`command:${ev.action}`] ? `command:${ev.action}` // her sohbet komutuna ayrı cümle
      : ev.kind;
    if (kind === 'gift' && (ev.total || 0) < (voiceCfg.giftMinCoins ?? 1)) return '';
    let chat = '';
    if (kind === 'chat') {
      if (ev.command) return ''; // oyun komutu: komutun kendi cümlesiyle okunur
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
      // kura: çekilen kartın tüm alanları değişken olur ({so}, {loai}, {tho}...), diziler virgülle birleştirilir
      ...Object.fromEntries(Object.entries(ev.draw || {}).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : v])),
    });
  }

  return { remember, line };
}

/** {anahtar} alanlarını doldurur; olmayan anahtar boş kalır. Doldurduktan sonra fazla noktalamayı toplar. */
export function fill(template, vars) {
  return String(template)
    .replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? '').toString())
    .replace(/\s+([.,!?])/g, '$1')
    .replace(/([.,!?]){2,}/g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();
}
