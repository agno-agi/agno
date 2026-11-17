// Đường ống xử lý: sự kiện chung từ mọi nguồn → lọc trùng → gom combo → luật → phiên live → phát cho theme.

import { createStreaks } from './streaks.js';
import { resolveGift, resolveChat, isJoinKeyword } from './rules.js';

export function createEngine({ getRules, session, catalog, emit, onChange, maxJoinsPerSecond = 15 }) {
  const streaks = createStreaks();
  const seen = new Map(); // eventId -> thời điểm, chống trùng khi nguồn gửi lặp
  const cooldowns = new Map();
  let bucket = { at: Date.now(), tokens: maxJoinsPerSecond };
  let lastEventAt = 0;

  function duplicate(id) {
    if (!id) return false;
    const now = Date.now();
    if (seen.has(id)) return true;
    seen.set(id, now);
    if (seen.size > 3000) for (const [k, t] of seen) { if (now - t > 600000 || seen.size > 2500) seen.delete(k); else break; }
    return false;
  }

  function takeJoinToken() {
    const now = Date.now();
    bucket.tokens = Math.min(maxJoinsPerSecond, bucket.tokens + ((now - bucket.at) / 1000) * maxJoinsPerSecond);
    bucket.at = now;
    if (bucket.tokens < 1) return false;
    bucket.tokens -= 1;
    return true;
  }

  const userView = (p) => ({ id: p.id, name: p.name, avatar: p.avatar, title: p.title, coins: p.coins, rank: session.rankOf(p.id), isPlayer: Boolean(p.joined) });
  const send = (kind, p, extra = {}) => emit({ kind, at: Date.now(), ...(p ? { user: userView(p) } : {}), ...extra });

  /** Cho người xem vào sân (nếu đủ điều kiện và chưa quá tải). */
  function join(p, reason) {
    if (p.joined) return;
    if (!takeJoinToken()) return;
    p.joined = true;
    session.bump('joins', 1);
    send('join', p, { reason });
  }

  function goals(hits) { for (const h of hits) emit({ kind: 'goal', at: Date.now(), ...h }); }

  function ingest(ev, { simulated = false } = {}) {
    if (!ev || duplicate(ev.eventId)) return;
    lastEventAt = Date.now();
    const rules = getRules();

    if (ev.kind === 'viewers') { session.setViewers(ev.viewers); return onChange(); }
    if (ev.kind === 'streamEnd') { emit({ kind: 'streamEnd', at: Date.now() }); return onChange(); }

    const { player: p, isNew } = session.touch(ev.user);
    if (isNew) p.joined = false;
    const openJoin = rules.joinMode === 'all';

    switch (ev.kind) {
      case 'member':
        if (openJoin) join(p, 'member');
        break;

      case 'chat': {
        p.chats += 1;
        session.bump('chats', 1);
        if (openJoin || isJoinKeyword(rules, ev.text)) join(p, 'chat');
        const cmd = resolveChat(rules, ev.text);
        send('chat', p, { text: ev.text, ...(cmd ? { command: cmd.action } : {}) });
        if (cmd && p.joined) {
          const key = `${p.id}:${cmd.action}`;
          if (!cmd.cooldownMs || Date.now() - (cooldowns.get(key) || 0) >= cmd.cooldownMs) {
            cooldowns.set(key, Date.now());
            send('command', p, { action: cmd.action, label: cmd.label, text: ev.text, ...(cmd.draw ? { draw: cmd.draw } : {}) });
          }
        }
        break;
      }

      case 'like':
        p.likes += ev.likeCount;
        if (openJoin) join(p, 'like');
        send('like', p, { count: ev.likeCount });
        goals(session.bump('likes', ev.likeCount));
        break;

      case 'follow':
      case 'share':
        join(p, ev.kind);
        send(ev.kind, p);
        goals(session.bump(ev.kind === 'follow' ? 'follows' : 'shares', 1));
        break;

      case 'gift': {
        const count = streaks.take(ev.user, ev.gift);
        if (!count) break;
        if (!simulated && catalog.learn(ev.gift)) emit({ kind: 'giftLearned', at: Date.now(), gift: ev.gift, internal: true });
        join(p, 'gift');
        const total = ev.gift.unitCoins * count;
        const titleUp = session.addCoins(p, total);
        const rule = resolveGift(rules, ev.gift);
        send('gift', p, {
          gift: { id: ev.gift.id, name: ev.gift.name, image: ev.gift.image, coins: ev.gift.unitCoins },
          count, total, action: rule.action, label: rule.label || ev.gift.name,
          big: total >= rules.bigGiftCoins, combo: ev.gift.streakable && !ev.gift.repeatEnd,
        });
        goals([...session.bump('coins', total), ...session.bump('gifts', count)]);
        if (titleUp) send('title', p, { title: titleUp });
        break;
      }
    }
    onChange();
  }

  return {
    ingest,
    get lastEventAt() { return lastEventAt; },
    reset() { streaks.clear(); seen.clear(); },
  };
}
