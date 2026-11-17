// Ghi nhớ các món quà đã gặp thật trên live (ID, tên, giá, ảnh) để bảng điều khiển cho chọn hành động riêng.

import fs from 'node:fs';
import path from 'node:path';

export function createGiftCatalog(file) {
  let gifts = {};
  try { gifts = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { /* chưa có */ }
  let timer = null;

  function learn(gift) {
    if (!gift.id) return false;
    const prev = gifts[gift.id];
    const next = { id: gift.id, name: gift.name, coins: gift.unitCoins, image: gift.image || prev?.image || '', seen: (prev?.seen || 0) + 1, lastSeen: Date.now() };
    gifts[gift.id] = next;
    if (!timer) timer = setTimeout(() => {
      timer = null;
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFile(file, JSON.stringify(gifts, null, 2), () => {});
    }, 3000);
    return !prev;
  }

  return { learn, list: () => Object.values(gifts).sort((a, b) => a.coins - b.coins || a.name.localeCompare(b.name)) };
}
