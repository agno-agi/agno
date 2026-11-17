// Ardışık hediyeler (kombo): TikTok aynı hediyeyi artan repeatCount ile (1, 2, 3...) tekrar tekrar gönderir,
// sonunda bir kez repeatEnd ile kapatır. Yalnızca ARTAN KISIM sayılır ki jeton iki kez eklenmesin,
// ve kapanışı beklemeden her kombo adımına hemen tepki verilir.

export function createStreaks({ ttlMs = 60000 } = {}) {
  const last = new Map(); // key -> { count, at }

  function take(user, gift, now = Date.now()) {
    if (!gift.streakable) return gift.repeatCount;
    const key = `${user.id}:${gift.id}:${gift.groupId}`;
    const prev = last.get(key)?.count || 0;
    const delta = Math.max(0, gift.repeatCount - prev);
    if (gift.repeatEnd) last.delete(key);
    else last.set(key, { count: Math.max(prev, gift.repeatCount), at: now });
    if (last.size > 500) for (const [k, v] of last) if (now - v.at > ttlMs) last.delete(k);
    return delta;
  }

  return { take, clear: () => last.clear() };
}
