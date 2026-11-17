// Quà tặng liên tiếp (combo): TikTok gửi lại cùng một món nhiều lần với repeatCount tăng dần
// (1, 2, 3...) rồi một lần chốt repeatEnd. Chỉ tính PHẦN TĂNG THÊM để không cộng trùng xu,
// và vẫn phản hồi ngay từng nhịp combo thay vì chờ chốt.

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
