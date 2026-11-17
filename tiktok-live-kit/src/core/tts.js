// Türkçe seslendirme (tr-TR) — kaynak: Microsoft Edge okuma servisi của Microsoft Edge (msedge-tts, miễn phí, cần mạng).
// Dịch vụ không chính thức, hay chập chờn: thử lại vài lần; theme bật voice.fallback = "local" thì lỗi hẳn
// sẽ đọc bằng giọng tiếng Việt có sẵn của Windows (Microsoft An, nghe máy hơn nhưng không cần mạng).
// Hàng đợi có giới hạn; câu quan trọng (priority) chen lên đầu, câu phụ (low) bị bỏ khi đang dồn.
// Câu lặp lại (đọc quẻ...) lưu ở cacheDir: lần sau phát ngay, không chờ dịch vụ. warm() đọc sẵn ở chế độ nền.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFile } from 'node:child_process';
import crypto from 'node:crypto';
import { MsEdgeTTS, OUTPUT_FORMAT } from 'msedge-tts';

export const VOICES = ['tr-TR-EmelNeural', 'tr-TR-AhmetNeural'];
const escXml = (s) => String(s).replace(/[<>&"']/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[c]));
const psQuote = (s) => `'${String(s).replace(/'/g, "''")}'`;
const PWSH = process.env.KIT_PWSH || 'pwsh';

export function createTTS({ dir, cacheDir, onReady, onError, maxQueue = 12, keepFiles = 40, synthesize }) {
  fs.mkdirSync(dir, { recursive: true });
  for (const f of fs.readdirSync(dir)) { try { fs.unlinkSync(path.join(dir, f)); } catch {} }
  if (cacheDir) fs.mkdirSync(cacheDir, { recursive: true });
  const queue = [];
  const warmQ = []; // câu đọc sẵn, chỉ làm khi rảnh
  let busy = false;
  let speaking = false; // đang làm câu thật (không tính đọc sẵn ở nền)
  let seq = 0;
  const cacheFile = (text, voice) => cacheDir && path.join(cacheDir, crypto.createHash('sha1').update(`${voice}|${text}`).digest('hex').slice(0, 20) + '.mp3');
  const pickVoice = (v) => (VOICES.includes(v) ? v : VOICES[0]);
  function publish(audio, ext, text, meta) {
    const file = `tts-${Date.now()}-${++seq}.${ext}`;
    fs.writeFileSync(path.join(dir, file), audio);
    onReady?.({ file, text, ...meta });
    const old = fs.readdirSync(dir).sort();
    while (old.length > keepFiles) { try { fs.unlinkSync(path.join(dir, old.shift())); } catch {} }
  }

  function say(text, opts = {}) {
    const t = String(text || '').trim().slice(0, 400);
    if (!t) return false;
    const cf = opts.cache && cacheFile(t, pickVoice(opts.voice));
    if (cf && fs.existsSync(cf)) { publish(fs.readFileSync(cf), 'mp3', t, opts.meta); return true; } // đã đọc sẵn: phát ngay
    if (opts.low && (speaking || queue.length)) return false; // câu phụ (chào, đọc bình luận) không chen khi đang có câu chờ; đọc sẵn ở nền thì không tính
    if (queue.length >= maxQueue) { onError?.('Ses kuyruğu dolu, 1 cümle atlandı'); return false; }
    if (opts.priority) { const i = queue.findIndex((q) => !q.opts.priority); queue.splice(i < 0 ? queue.length : i, 0, { text: t, opts }); }
    else queue.push({ text: t, opts });
    pump();
    return true;
  }

  async function synth(text, voice, timeoutMs) {
    const tts = new MsEdgeTTS();
    try {
      await tts.setMetadata(voice, OUTPUT_FORMAT.AUDIO_24KHZ_48KBITRATE_MONO_MP3);
      // Dịch vụ hiện chỉ nhận tốc độ / cao độ mặc định (đổi là đóng kết nối, đã thử 11/2026), nên để nguyên mặc định.
      const { audioStream } = tts.toStream(escXml(text));
      const chunks = [];
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('zaman aşımı')), timeoutMs);
        audioStream.on('data', (c) => chunks.push(c));
        audioStream.on('end', () => { clearTimeout(timer); resolve(); });
        audioStream.on('error', (e) => { clearTimeout(timer); reject(e); });
      });
      if (!chunks.length) throw new Error('ses alınamadı');
      return Buffer.concat(chunks);
    } finally { try { tts.close(); } catch {} }
  }

  // Windows'ta kurulu Türkçe ses (System.Speech), WAV dosyası çıkarır
  function localSynth(text) {
    return new Promise((resolve, reject) => {
      const base = path.join(os.tmpdir(), `kit-tts-${process.pid}-${++seq}`);
      fs.writeFileSync(`${base}.txt`, text, 'utf8');
      const ps = [
        'Add-Type -AssemblyName System.Speech',
        '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer',
        "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'tr-TR' } | Select-Object -First 1",
        'if (-not $v) { exit 3 }',
        '$s.SelectVoice($v.VoiceInfo.Name)',
        '$s.Rate = -1',
        `$s.SetOutputToWaveFile(${psQuote(`${base}.wav`)})`,
        `$s.Speak([IO.File]::ReadAllText(${psQuote(`${base}.txt`)}, [Text.Encoding]::UTF8))`,
        '$s.Dispose()',
      ].join('; ');
      // PowerShell 7 (pwsh) thấy cả giọng OneCore như Microsoft An; Windows PowerShell 5 chỉ thấy giọng SAPI cũ
      execFile(PWSH, ['-NoProfile', '-NonInteractive', '-Command', ps], { timeout: 20000, windowsHide: true }, (err) => {
        try { fs.unlinkSync(`${base}.txt`); } catch {}
        if (err) return reject(err.code === 3 ? new Error('bilgisayarda Türkçe ses yok') : err);
        try { const buf = fs.readFileSync(`${base}.wav`); fs.unlinkSync(`${base}.wav`); resolve(buf); } catch (e) { reject(e); }
      });
    });
  }

  // Dịch vụ chặn tạm khi gửi dồn: thử tối đa 3 lần, giãn dần
  async function pump() {
    if (busy || (!queue.length && !warmQ.length)) return;
    busy = true;
    const { text, opts } = queue.length ? queue.shift() : warmQ.shift();
    speaking = !opts.warm;
    const voice = pickVoice(opts.voice);
    let audio = null, ext = 'mp3', lastErr = null;
    for (let tryNo = 0; tryNo < 3 && !audio; tryNo++) {
      if (tryNo) await new Promise((r) => setTimeout(r, 800 * tryNo));
      try { audio = await (synthesize || synth)(text, voice, 12000); } catch (err) { lastErr = err; }
    }
    if (!audio && opts.fallback === 'local' && process.platform === 'win32') {
      try { audio = await localSynth(text); ext = 'wav'; } catch (err) { lastErr = err; }
    }
    if (audio && opts.cache && ext === 'mp3') { try { fs.writeFileSync(cacheFile(text, voice), audio); } catch {} }
    if (audio && !opts.warm) publish(audio, ext, text, opts.meta);
    else if (!audio && !opts.warm) onError?.(`Ses okuma hatası: ${lastErr?.message || lastErr}`);
    busy = false;
    speaking = false;
    setTimeout(pump, opts.warm && !queue.length ? 1200 : 300); // đọc sẵn thì giãn ra cho dịch vụ khỏi chặn; có câu thật chờ thì làm ngay
  }

  /** Đọc sẵn các câu (chưa có trong bộ nhớ) ở chế độ nền, để lúc cần phát ngay. */
  function warm(texts, voice) {
    if (!cacheDir) return 0;
    const v = pickVoice(voice);
    let n = 0;
    for (const raw of texts) {
      const t = String(raw || '').trim().slice(0, 400);
      if (!t || fs.existsSync(cacheFile(t, v)) || warmQ.some((w) => w.text === t)) continue;
      warmQ.push({ text: t, opts: { voice: v, cache: true, warm: true } });
      n++;
    }
    pump();
    return n;
  }

  return { say, warm, get pending() { return queue.length; } };
}
