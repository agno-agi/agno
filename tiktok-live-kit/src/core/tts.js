// Türkçe seslendirme (tr-TR): Microsoft Edge okuma servisi üzerinden (msedge-tts, ücretsiz, internet gerekir).
// Servis resmi değildir ve kararsızdır: birkaç kez yeniden denenir; temada voice.fallback = "local" ise tamamen
// başarısız olunca Windows'ta kurulu Türkçe ses okur (daha robotik ama internet gerektirmez).
// Kuyruk sınırlıdır; önemli cümleler (priority) öne geçer, ikincil cümleler (low) yoğunlukta atlanır.
// Tekrarlanan cümleler (dua/sabit metin) cacheDir'e kaydedilir: sonraki sefer anında çalar. warm() arka planda önceden okur.

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
  const warmQ = []; // önceden okunacak cümleler, yalnızca boştayken işlenir
  let busy = false;
  let speaking = false; // gerçek bir cümle işleniyor (arka plandaki ön okuma sayılmaz)
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
    if (cf && fs.existsSync(cf)) { publish(fs.readFileSync(cf), 'mp3', t, opts.meta); return true; } // zaten okunmuş: hemen çal
    if (opts.low && (speaking || queue.length)) return false; // ikincil cümle (selam, yorum okuma) bekleyen cümle varken araya girmez; arka plan ön okuması sayılmaz
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
      // Servis şu an yalnızca varsayılan hız / ses perdesini kabul ediyor (değiştirince bağlantıyı kapatıyor, 11/2026'da denendi); varsayılan bırakılır.
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
      // PowerShell 7 (pwsh) OneCore seslerini de görür; Windows PowerShell 5 yalnızca eski SAPI seslerini görür
      execFile(PWSH, ['-NoProfile', '-NonInteractive', '-Command', ps], { timeout: 20000, windowsHide: true }, (err) => {
        try { fs.unlinkSync(`${base}.txt`); } catch {}
        if (err) return reject(err.code === 3 ? new Error('bilgisayarda Türkçe ses yok') : err);
        try { const buf = fs.readFileSync(`${base}.wav`); fs.unlinkSync(`${base}.wav`); resolve(buf); } catch (e) { reject(e); }
      });
    });
  }

  // Servis yoğun gönderimde geçici engelleyebilir: en fazla 3 deneme, aralık giderek açılır
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
    setTimeout(pump, opts.warm && !queue.length ? 1200 : 300); // ön okumada aralık açılır ki servis engellemesin; gerçek cümle bekliyorsa hemen işlenir
  }

  /** Cümleleri (henüz önbellekte olmayanları) arka planda önceden okur, gerektiğinde anında çalsın. */
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
