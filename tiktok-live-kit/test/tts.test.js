import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createTTS } from '../src/core/tts.js';

const tmpDir = (name) => fs.mkdtempSync(path.join(os.tmpdir(), `tlk-tts-${name}-`));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Sahte okuma servisi: serbest bırakılana kadar bekler, böylece bir cümle "okunuyor" durumunda tutulur
function fakeSynth() {
  const pending = [];
  const synthesize = (text) => new Promise((resolve) => pending.push(() => resolve(Buffer.from(text))));
  return { synthesize, release: () => pending.shift()?.(), get waiting() { return pending.length; } };
}

test('tts: yalnızca arka planda ön okuma varken ikincil cümle yine okunur', async () => {
  const fake = fakeSynth();
  const ready = [];
  const tts = createTTS({ dir: tmpDir('out'), cacheDir: tmpDir('cache'), synthesize: fake.synthesize, onReady: (r) => ready.push(r.text) });
  tts.warm(['câu đọc sẵn 1', 'câu đọc sẵn 2']);
  assert.equal(fake.waiting, 1); // 1. cümle ön okunuyor
  assert.equal(tts.say('Chào An!', { low: true }), true);
  fake.release(); // ön okuma bitti: ana kuyruk ön okuma kuyruğundan önce işlenir
  await wait(400);
  fake.release();
  await wait(50);
  assert.deepEqual(ready, ['Chào An!']);
});

test('tts: gerçek cümle okunurken ikincil cümle atlanır', async () => {
  const fake = fakeSynth();
  const tts = createTTS({ dir: tmpDir('out'), synthesize: fake.synthesize });
  assert.equal(tts.say('Cảm ơn An đã tặng hoa hồng', { priority: true }), true);
  assert.equal(tts.say('Chào Bình!', { low: true }), false);
  fake.release();
});
