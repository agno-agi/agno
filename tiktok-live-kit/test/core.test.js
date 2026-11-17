import { test } from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { normalize, normalizeTikFinity, plain } from '../src/core/normalize.js';
import { createStreaks } from '../src/core/streaks.js';
import { sanitizeRules, resolveGift, resolveChat, isJoinKeyword } from '../src/core/rules.js';
import { createSession } from '../src/core/session.js';
import { createEngine } from '../src/core/engine.js';

const tmp = (name) => path.join(os.tmpdir(), `tlk-test-${process.pid}-${name}.json`);

test('normalize: dạng tiktok-live-connector (giftDetails, user.uniqueId)', () => {
  const ev = normalize('gift', {
    giftId: 5655, repeatCount: 3, repeatEnd: false, groupId: 'g1',
    user: { uniqueId: 'oanh_luu', userId: '123', nickname: 'oanh luu', profilePictureUrl: 'https://x/a.jpeg' },
    giftDetails: { giftName: 'Rose', diamondCount: 1, giftType: 1 },
    common: { msgId: 'm1' },
  });
  assert.equal(ev.kind, 'gift');
  assert.equal(ev.eventId, 'm1');
  assert.deepEqual(ev.user, { id: '123', uniqueId: 'oanh_luu', name: 'oanh luu', avatar: 'https://x/a.jpeg' });
  assert.equal(ev.gift.name, 'Rose');
  assert.equal(ev.gift.unitCoins, 1);
  assert.equal(ev.gift.streakable, true);
  assert.equal(ev.gift.repeatEnd, false);
});

test('normalize: dạng proto v3 (gift, displayId, avatarThumb.mUrls)', () => {
  const ev = normalize('gift', {
    giftId: '5487', repeatCount: 1, repeatEnd: 1,
    user: { id: '9', displayId: 'pnthinh', nickname: 'Pnthinh', avatarThumb: { mUrls: ['https://p/a.webp', 'https://p/a.jpeg'] } },
    gift: { name: 'Finger Heart', diamondCount: 5, type: 2 },
  });
  assert.equal(ev.user.uniqueId, 'pnthinh');
  assert.equal(ev.user.avatar, 'https://p/a.jpeg', 'ưu tiên ảnh jpeg');
  assert.equal(ev.gift.unitCoins, 5);
  assert.equal(ev.gift.streakable, false);
});

test('normalizeTikFinity: {event,data}, mảng, chuỗi JSON; bỏ tin lạ', () => {
  const raw = JSON.stringify([
    { event: 'chat', data: { uniqueId: 'a', nickname: 'A', comment: 'Nam mô' } },
    { event: 'like', data: { uniqueId: 'b', likeCount: 7, totalLikeCount: 100 } },
    { event: 'roomUser', data: { viewerCount: 42 } },
    { event: 'somethingElse', data: {} },
  ]);
  const evs = normalizeTikFinity(raw);
  assert.equal(evs.length, 3);
  assert.equal(evs[0].text, 'Nam mô');
  assert.equal(evs[1].likeCount, 7);
  assert.equal(evs[2].viewers, 42);
  assert.deepEqual(normalizeTikFinity('không phải json'), []);
});

test('social → follow / share', () => {
  assert.equal(normalize('social', { displayType: 'pm_mt_msg_viewer_follow', user: { uniqueId: 'x' } }).kind, 'follow');
  assert.equal(normalize('social', { displayType: 'pm_mt_msg_viewer_share', user: { uniqueId: 'x' } }).kind, 'share');
});

test('plain: bỏ dấu tiếng Việt, đ → d', () => {
  assert.equal(plain('  Quán  Cà PHÊ  '), 'quan ca phe');
  assert.equal(plain('Hoa Hồng'), 'hoa hong');
});

test('streaks: combo chỉ tính phần tăng, không cộng trùng', () => {
  const st = createStreaks();
  const u = { id: 'u1' };
  const g = (n, end) => ({ id: '5655', groupId: 'g', streakable: true, repeatCount: n, repeatEnd: end });
  const deltas = [g(1, false), g(2, false), g(3, false), g(5, false), g(5, true)].map((x) => st.take(u, x));
  assert.deepEqual(deltas, [1, 1, 1, 2, 0]);
  assert.equal(deltas.reduce((a, b) => a + b), 5, 'tổng đúng 5 món');
  // nguồn chỉ gửi lần chốt (không có nhịp giữa)
  assert.equal(st.take(u, { ...g(4, true), groupId: 'h' }), 4);
  // quà không combo
  assert.equal(st.take(u, { id: 'x', streakable: false, repeatCount: 2 }), 2);
});

const RULES = sanitizeRules({
  joinMode: 'keyword', joinKeywords: 'xin chao, chao ca nha',
  giftTiers: [{ minCoins: 10, action: 'big' }, { minCoins: 1, action: 'small' }, { minCoins: 5, action: 'bow' }],
  giftOverrides: [{ giftId: '8913', action: 'grand', label: 'Đặc biệt' }, { names: 'hoa hồng, rose', action: 'bow' }],
  chatCommands: [{ keywords: ['chúc'], match: 'exact', action: 'wish' }, { keywords: 'chúc mừng', match: 'contains', action: 'wish' }],
}, ['small', 'bow', 'big', 'grand', 'wish']);

test('rules: ID quà → tên quà → bậc giá', () => {
  assert.equal(resolveGift(RULES, { id: '8913', name: 'Rosa', unitCoins: 10 }).action, 'grand');
  assert.equal(resolveGift(RULES, { id: '1', name: 'Hoa Hồng', unitCoins: 1 }).action, 'bow');
  assert.equal(resolveGift(RULES, { id: '2', name: 'GG', unitCoins: 1 }).action, 'small');
  assert.equal(resolveGift(RULES, { id: '3', name: 'X', unitCoins: 7 }).action, 'bow');
  assert.equal(resolveGift(RULES, { id: '4', name: 'Y', unitCoins: 99 }).action, 'big');
});

test('rules: lệnh chat và từ khoá vào sân (không dấu, hoa thường)', () => {
  assert.equal(resolveChat(RULES, 'CHÚC')?.action, 'wish');
  assert.equal(resolveChat(RULES, 'chúc mừng cả nhà ạ')?.action, 'wish');
  assert.equal(resolveChat(RULES, 'chạy đi'), null);
  assert.ok(isJoinKeyword(RULES, 'Xin Chào cả nhà'));
  assert.ok(!isJoinKeyword(RULES, 'tạm biệt'));
});

test('rules: hành động không có trong theme thì về hành động đầu tiên', () => {
  const r = sanitizeRules({ giftTiers: [{ minCoins: 1, action: 'khong-co' }] }, ['a', 'b']);
  assert.equal(r.giftTiers[0].action, 'a');
});

function harness(rules = RULES) {
  const out = [];
  const session = createSession({ file: tmp(Math.random().toString(36).slice(2)), titles: [{ minCoins: 0, label: 'Khách' }, { minCoins: 10, label: 'Fan cứng' }], goals: [{ id: 'likes', metric: 'likes', every: 100 }] });
  const engine = createEngine({ getRules: () => rules, session, catalog: { learn: () => false }, emit: (e) => out.push(e), onChange: () => {} });
  return { out, session, engine, kinds: () => out.map((e) => e.kind) };
}
const user = (id) => ({ id, uniqueId: id, name: id.toUpperCase(), avatar: '' });

test('engine: chế độ từ khoá — chỉ vào sân khi chat từ khoá / tặng quà', () => {
  const h = harness();
  h.engine.ingest({ kind: 'member', user: user('a') });
  h.engine.ingest({ kind: 'chat', user: user('a'), text: 'hello' });
  assert.deepEqual(h.kinds(), ['chat']);
  assert.equal(h.out[0].user.isPlayer, false);
  h.engine.ingest({ kind: 'chat', user: user('a'), text: 'chào cả nhà' });
  assert.deepEqual(h.kinds(), ['chat', 'join', 'chat']);
  h.engine.ingest({ kind: 'gift', user: user('b'), gift: { id: '2', name: 'GG', unitCoins: 1, streakable: false, repeatCount: 1, repeatEnd: true } });
  assert.deepEqual(h.kinds().slice(-2), ['join', 'gift']);
});

test('engine: lọc trùng theo eventId, combo + danh hiệu + mục tiêu', () => {
  const h = harness({ ...RULES, joinMode: 'all' });
  const like = { kind: 'like', eventId: 'L1', user: user('a'), likeCount: 60 };
  h.engine.ingest(like);
  h.engine.ingest(like); // trùng
  h.engine.ingest({ kind: 'like', eventId: 'L2', user: user('a'), likeCount: 60 });
  assert.equal(h.session.data.totals.likes, 120);
  assert.equal(h.out.filter((e) => e.kind === 'goal').length, 1, 'đạt mốc 100 tim một lần');

  const g = (n, end) => ({ kind: 'gift', user: user('b'), gift: { id: '5655', name: 'Rose', unitCoins: 1, streakable: true, repeatCount: n, repeatEnd: end, groupId: 'x' } });
  for (const e of [g(4, false), g(8, false), g(12, true)]) h.engine.ingest(e);
  const gifts = h.out.filter((e) => e.kind === 'gift');
  assert.deepEqual(gifts.map((e) => e.count), [4, 4, 4]);
  assert.equal(h.session.data.players.b.coins, 12);
  assert.equal(h.out.filter((e) => e.kind === 'title').length, 1, 'lên Fan cứng đúng một lần');
  assert.equal(h.session.top(1)[0].id, 'b');
});

test('engine: lệnh chat có thời gian chờ', () => {
  const h = harness({ ...RULES, joinMode: 'all', chatCommands: [{ keywords: ['chuc'], match: 'exact', action: 'wish', label: '', cooldownMs: 60000 }] });
  for (let i = 0; i < 3; i++) h.engine.ingest({ kind: 'chat', user: user('a'), text: 'chúc' });
  assert.equal(h.out.filter((e) => e.kind === 'command').length, 1);
});
