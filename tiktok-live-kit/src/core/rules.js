// Luật: quà nào / lệnh chat nào → hành động nào của theme.
// Thứ tự ưu tiên cho quà: đúng ID quà → đúng tên quà (bí danh, không dấu) → bậc theo giá một món.

import { plain } from './normalize.js';

export function sanitizeRules(input = {}, actionIds = []) {
  const okAction = (a) => (actionIds.length === 0 || actionIds.includes(a) ? a : actionIds[0] || 'default');
  const list = (v, n = 100) => (Array.isArray(v) ? v.slice(0, n) : []);
  const words = (v) => (Array.isArray(v) ? v : String(v || '').split(',')).map((x) => String(x).trim()).filter(Boolean).slice(0, 20);
  return {
    joinMode: input.joinMode === 'keyword' ? 'keyword' : 'all',
    joinKeywords: words(input.joinKeywords),
    bigGiftCoins: Math.max(1, Number(input.bigGiftCoins) || 100),
    giftTiers: list(input.giftTiers, 20)
      .map((t) => ({ minCoins: Math.max(1, Number(t.minCoins) || 1), action: okAction(t.action), label: String(t.label || '').slice(0, 40) }))
      .sort((a, b) => a.minCoins - b.minCoins),
    giftOverrides: list(input.giftOverrides)
      .map((o) => ({ giftId: String(o.giftId || '').slice(0, 40), names: words(o.names), action: okAction(o.action), label: String(o.label || '').slice(0, 40) }))
      .filter((o) => o.giftId || o.names.length),
    chatCommands: list(input.chatCommands, 50)
      .map((c) => ({ keywords: words(c.keywords), match: c.match === 'contains' ? 'contains' : 'exact', action: okAction(c.action), label: String(c.label || '').slice(0, 40), cooldownMs: Math.max(0, Number(c.cooldownMs) || 0), ...(c.draw ? { draw: String(c.draw).slice(0, 40) } : {}) }))
      .filter((c) => c.keywords.length),
  };
}

export function resolveGift(rules, gift) {
  const byId = gift.id && rules.giftOverrides.find((o) => o.giftId && o.giftId === String(gift.id));
  if (byId) return { action: byId.action, label: byId.label, via: 'id' };
  const name = plain(gift.name);
  const byName = rules.giftOverrides.find((o) => o.names.some((n) => plain(n) === name));
  if (byName) return { action: byName.action, label: byName.label, via: 'name' };
  const tier = [...rules.giftTiers].reverse().find((t) => gift.unitCoins >= t.minCoins) || rules.giftTiers[0];
  return tier ? { action: tier.action, label: tier.label, via: 'tier' } : { action: 'default', label: gift.name, via: 'none' };
}

const matches = (keywords, match, msg) => keywords.some((k) => (match === 'contains' ? msg.includes(plain(k)) : msg === plain(k)));

export function resolveChat(rules, textValue) {
  const msg = plain(textValue);
  if (!msg) return null;
  return rules.chatCommands.find((c) => matches(c.keywords, c.match, msg)) || null;
}

export const isJoinKeyword = (rules, textValue) => matches(rules.joinKeywords, 'contains', plain(textValue));
