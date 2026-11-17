// TikFinity Desktop kaynağı: TikFinity kanal sahibinin TikTok hesabıyla girer ve olayları yerel WebSocket'te yayınlar.
// Olaylar TikFinity'nin bağlı olduğu canlı oturuma aittir; kontrol panelinde girilen kanal adı yalnızca gösterim içindir.

import WebSocket from 'ws';
import { normalizeTikFinity } from '../core/normalize.js';

export function createTikFinity({ url, onEvent, onStatus }) {
  let ws = null;

  return {
    name: 'tikfinity',
    start() {
      return new Promise((resolve, reject) => {
        const sock = new WebSocket(url, { handshakeTimeout: 3000 });
        ws = sock;
        let opened = false;
        sock.on('open', () => { opened = true; resolve(); });
        sock.on('message', (raw) => { if (ws === sock) for (const ev of normalizeTikFinity(raw)) onEvent(ev); });
        sock.on('error', (err) => { if (!opened) reject(new Error(`TikFinity bulunamadı: ${url} (${err.code || err.message})`)); });
        sock.on('close', () => { if (ws === sock && opened) { ws = null; onStatus('lost', 'TikFinity bağlantıyı kapattı'); } });
      });
    },
    async stop() { const s = ws; ws = null; try { s?.terminate(); } catch {} },
  };
}
