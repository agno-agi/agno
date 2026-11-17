import { cleanName, cleanChat } from './profanity.js';

// Đưa dữ liệu thô của mọi nguồn (tiktok-live-connector, TikFinity, giả lập) về MỘT dạng sự kiện chung.
// Tên trường đổi giữa các bản thư viện và giữa các nguồn, nên đọc phòng thủ.

const KIND_ALIASES = {
  member: 'member', join: 'member', viewerjoin: 'member',
  chat: 'chat', comment: 'chat', message: 'chat',
  like: 'like',
  gift: 'gift',
  follow: 'follow',
  share: 'share',
  roomuser: 'viewers', viewers: 'viewers', viewercount: 'viewers',
  social: 'social',
  streamend: 'streamEnd', liveend: 'streamEnd',
};

export const kindOf = (name) => KIND_ALIASES[String(name || '').toLowerCase().replace(/[^a-z]/g, '')] || null;

const isUrl = (v) => typeof v === 'string' && /^https:\/\//i.test(v);
const firstUrl = (...vals) => vals.flatMap((v) => (Array.isArray(v) ? v : [v])).find(isUrl) || '';
const text = (...vals) => {
  for (const v of vals) {
    if (typeof v === 'string' && v.trim()) return v.trim();
    if (typeof v === 'number' && Number.isFinite(v)) return String(v);
  }
  return '';
};
const clean = (s, max) => String(s ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, max);

export function normUser(data = {}) {
  const u = data.user || data.userData || data.author || data;
  const uniqueId = text(u.uniqueId, u.unique_id, u.displayId, u.username, data.uniqueId);
  const id = text(u.userId, u.user_id, u.id, data.userId, uniqueId, u.nickname) || 'an-danh';
  // Ưu tiên ảnh JPEG/PNG: một số trình duyệt nhúng (OBS cũ) không giải mã được WebP của TikTok
  const pics = [
    u.profilePictureUrl, u.profilePictureUrls, u.profilePicture?.urls, u.profilePicture?.urlList,
    u.avatarThumb?.urlList, u.avatarThumb?.mUrls, u.avatarMedium?.urlList, u.avatarMedium?.mUrls,
    u.userDetails?.profilePictureUrls, data.profilePictureUrl,
  ].flatMap((v) => (Array.isArray(v) ? v : [v])).filter(isUrl);
  return {
    id: clean(id, 128),
    uniqueId: clean(uniqueId || id, 64),
    name: cleanName(clean(text(u.nickname, u.displayName, uniqueId), 60)) || 'Misafir',
    avatar: pics.find((p) => /\.(jpe?g|png)(?:[?~]|$)/i.test(p)) || pics[0] || '',
  };
}

function normGift(data) {
  const d = data.giftDetails || data.gift || {};
  const ext = data.extendedGiftInfo || {};
  const repeatCount = Math.max(1, Number(data.repeatCount ?? data.repeat_count) || 1);
  const type = Number(d.giftType ?? d.type ?? data.giftType ?? ext.type);
  return {
    id: text(data.giftId, data.gift_id, d.id, d.giftId),
    name: clean(text(d.giftName, d.name, data.giftName, ext.name), 60) || 'Hediye',
    image: firstUrl(data.giftPictureUrl, d.giftImage?.giftPictureUrl, d.giftImage?.urlList, d.giftImage?.mUrls, d.image?.urlList, d.image?.mUrls, ext.image?.url_list),
    unitCoins: Math.max(0, Number(d.diamondCount ?? d.diamond_count ?? ext.diamond_count ?? data.diamondCount) || 0) || 1,
    streakable: type === 1,
    repeatCount,
    // nguồn không báo repeatEnd thì coi như quà đã chốt
    repeatEnd: data.repeatEnd === undefined ? true : Boolean(data.repeatEnd),
    groupId: text(data.groupId, data.group_id),
  };
}

/** Một sự kiện thô → sự kiện chung, hoặc null nếu không dùng tới. */
export function normalize(kindName, data = {}) {
  let kind = kindOf(kindName);
  if (!kind) return null;
  if (kind === 'social') {
    const t = String(data.displayType || data.label || '').toLowerCase();
    kind = t.includes('follow') ? 'follow' : t.includes('share') ? 'share' : null;
    if (!kind) return null;
  }
  const eventId = text(data.msgId, data.common?.msgId, data.event?.msgId, data.eventId);
  if (kind === 'viewers') return { kind, eventId, viewers: Number(data.viewerCount ?? data.total ?? data.totalUser) || 0 };
  if (kind === 'streamEnd') return { kind, eventId };
  const ev = { kind, eventId, user: normUser(data) };
  if (kind === 'chat') ev.text = cleanChat(clean(text(data.comment, data.content, data.message, data.text), 200)); // küfürlü sohbet boş metne döner
  if (kind === 'like') {
    ev.likeCount = Math.max(1, Number(data.likeCount ?? data.count) || 1);
    ev.totalLikes = Number(data.totalLikeCount ?? data.total) || 0;
  }
  if (kind === 'gift') ev.gift = normGift(data);
  return ev;
}

/** Tin nhắn TikFinity: {event, data} hoặc mảng các tin đó. */
export function normalizeTikFinity(raw) {
  let msg = raw;
  if (Buffer.isBuffer(msg)) msg = msg.toString('utf8');
  if (typeof msg === 'string') { try { msg = JSON.parse(msg); } catch { return []; } }
  return (Array.isArray(msg) ? msg : [msg])
    .map((m) => m && typeof m === 'object' ? normalize(m.event || m.type || m.eventType, m.data && typeof m.data === 'object' ? m.data : m) : null)
    .filter(Boolean);
}

/** Aksan/diyakritik at, ı→i, đ→d, küçük harf: hediye adı ve sohbet komutu eşleştirme (Türkçe + Vietnamca). */
export const plain = (s) => String(s || '').replace(/[ıİ]/g, 'i').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'd').toLowerCase().replace(/\s+/g, ' ').trim();
