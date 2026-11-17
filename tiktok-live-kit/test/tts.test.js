import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createTTS } from '../src/core/tts.js';

const tmpDir = (name) => fs.mkdtempSync(path.join(os.tmpdir(), `tlk-tts-${name}-`));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Dịch vụ đọc giả: chờ đến khi được thả ra, để giữ một câu "đang đọc"
function fakeSynth() {
  const pending = [];
  const synthesize = (text) => new Promise((resolve) => pending.push(() => resolve(Buffer.from(text))));
  return { synthesize, release: () => pending.shift()?.(), get waiting() { return pending.length; } };
}

test('tts: câu phụ vẫn đọc khi chỉ đang đọc sẵn ở nền', async () => {
  const fake = fakeSynth();
  const ready = [];
  const tts = createTTS({ dir: tmpDir('out'), cacheDir: tmpDir('cache'), synthesize: fake.synthesize, onReady: (r) => ready.push(r.text) });
  tts.warm(['câu đọc sẵn 1', 'câu đọc sẵn 2']);
  assert.equal(fake.waiting, 1); // đang đọc sẵn câu 1
  assert.equal(tts.say('Chào An!', { low: true }), true);
  fake.release(); // xong câu đọc sẵn: hàng chính được làm trước hàng đọc sẵn
  await wait(400);
  fake.release();
  await wait(50);
  assert.deepEqual(ready, ['Chào An!']);
});

test('tts: câu phụ bị bỏ khi đang đọc câu thật', async () => {
  const fake = fakeSynth();
  const tts = createTTS({ dir: tmpDir('out'), synthesize: fake.synthesize });
  assert.equal(tts.say('Cảm ơn An đã tặng hoa hồng', { priority: true }), true);
  assert.equal(tts.say('Chào Bình!', { low: true }), false);
  fake.release();
});
