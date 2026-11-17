// Trạng thái một phiên live: người chơi, bảng xếp hạng, danh hiệu, mục tiêu, thống kê.
// Lưu xuống file để tắt mở server (hay mất điện) giữa buổi live không mất bảng xếp hạng.

import fs from 'node:fs';
import path from 'node:path';

export function createSession({ file, titles = [], goals = [], playerTtlMs = 20 * 60000 } = {}) {
  const sortedTitles = [...titles].sort((a, b) => a.minCoins - b.minCoins);
  let s = blank();
  load();

  function blank() {
    return {
      startedAt: Date.now(),
      players: {}, // id -> { id, name, avatar, coins, likes, gifts, chats, title, joinedAt, lastActive }
      totals: { coins: 0, likes: 0, gifts: 0, chats: 0, joins: 0, follows: 0, shares: 0 },
      viewers: 0,
      goals: goals.map((g) => ({ id: g.id, metric: g.metric, label: g.label || g.metric, every: Math.max(1, g.every || 1000), reached: 0 })),
    };
  }

  function load() {
    try {
      const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
      s = { ...blank(), ...saved, goals: blank().goals.map((g) => ({ ...g, reached: saved.goals?.find((x) => x.id === g.id)?.reached || 0 })) };
    } catch { /* chưa có phiên cũ */ }
  }

  let saveTimer = null;
  function save() {
    if (!file || saveTimer) return;
    saveTimer = setTimeout(() => {
      saveTimer = null;
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFile(file + '.tmp', JSON.stringify(s), (err) => { if (!err) fs.rename(file + '.tmp', file, () => {}); });
    }, 1500);
  }

  const titleFor = (coins) => [...sortedTitles].reverse().find((t) => coins >= t.minCoins)?.label || '';

  function touch(user) {
    const now = Date.now();
    let p = s.players[user.id];
    const isNew = !p || now - p.lastActive > playerTtlMs;
    if (!p) {
      p = s.players[user.id] = { id: user.id, name: user.name, avatar: user.avatar, coins: 0, likes: 0, gifts: 0, chats: 0, title: titleFor(0), joinedAt: now, lastActive: now };
    }
    p.name = user.name || p.name;
    if (user.avatar) p.avatar = user.avatar;
    p.lastActive = now;
    save();
    return { player: p, isNew };
  }

  /** Cộng một chỉ số; trả về các mục tiêu vừa đạt. */
  function bump(metric, n) {
    s.totals[metric] = (s.totals[metric] || 0) + n;
    const hits = [];
    for (const g of s.goals) {
      if (g.metric !== metric) continue;
      const step = Math.floor(s.totals[metric] / g.every);
      if (step > g.reached) { g.reached = step; hits.push({ goal: g.id, label: g.label, value: step * g.every }); }
    }
    save();
    return hits;
  }

  /** Cộng xu cho người tặng; trả về danh hiệu mới nếu vừa lên bậc. */
  function addCoins(p, coins) {
    p.coins += coins;
    p.gifts += 1;
    const t = titleFor(p.coins);
    const up = t && t !== p.title ? t : null;
    p.title = t;
    return up;
  }

  const view = (p, rank) => ({ id: p.id, name: p.name, avatar: p.avatar, coins: p.coins, title: p.title, rank });

  function top(n = 10) {
    return Object.values(s.players).filter((p) => p.coins > 0).sort((a, b) => b.coins - a.coins).slice(0, n).map((p, i) => view(p, i + 1));
  }

  function active(max = 300) {
    const cutoff = Date.now() - playerTtlMs;
    const ranks = new Map(top(3).map((p) => [p.id, p.rank]));
    return Object.values(s.players).filter((p) => p.lastActive >= cutoff)
      .sort((a, b) => b.lastActive - a.lastActive).slice(0, max).map((p) => view(p, ranks.get(p.id) || 0));
  }

  function goalsView() {
    return s.goals.map((g) => {
      const value = s.totals[g.metric] || 0;
      return { id: g.id, label: g.label, value, target: (g.reached + 1) * g.every, progress: (value % g.every) / g.every };
    });
  }

  function reset() { s = blank(); save(); }

  function csv() {
    const rows = Object.values(s.players).filter((p) => p.coins > 0 || p.chats > 0).sort((a, b) => b.coins - a.coins);
    const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
    return '﻿Sıra,ID,İsim,Jeton,Hediye sayısı,Beğeni,Yorum,Unvan\n' +
      rows.map((p, i) => [i + 1, p.id, p.name, p.coins, p.gifts, p.likes, p.chats, p.title].map(q).join(',')).join('\n');
  }

  return {
    get data() { return s; },
    touch, bump, addCoins, top, active, goalsView, reset, csv, save,
    setViewers(n) { s.viewers = n; },
    rankOf(id) { return top(3).find((p) => p.id === id)?.rank || 0; },
  };
}
