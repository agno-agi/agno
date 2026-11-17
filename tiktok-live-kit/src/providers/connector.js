// tiktok-live-connector kütüphanesiyle doğrudan kaynak (resmi değil, Euler Stream üzerinden imzalanır).
// Ek kurulum gerekmez, yalnızca canlı yayındaki kanal adı yeterli.

import { TikTokLiveConnection, WebcastEvent, ControlEvent } from 'tiktok-live-connector';
import { normalize } from '../core/normalize.js';

const EVENTS = {
  member: WebcastEvent.MEMBER, chat: WebcastEvent.CHAT, like: WebcastEvent.LIKE, gift: WebcastEvent.GIFT,
  follow: WebcastEvent.FOLLOW, share: WebcastEvent.SHARE, roomUser: WebcastEvent.ROOM_USER, streamEnd: WebcastEvent.STREAM_END,
};

export function createConnector({ username, signApiKey, onEvent, onStatus }) {
  let conn = null;

  return {
    name: 'connector',
    async start() {
      if (!username) throw new Error('TikTok kanal adı girilmedi');
      const c = new TikTokLiveConnection(username, {
        enableExtendedGiftInfo: true,
        processInitialData: false,
        ...(signApiKey ? { signApiKey } : {}),
      });
      conn = c;
      for (const [kind, name] of Object.entries(EVENTS)) {
        c.on(name, (data) => { if (conn === c) { const ev = normalize(kind, data); if (ev) onEvent(ev); } });
      }
      c.on(ControlEvent.ERROR, (e) => console.warn('[connector]', e?.info || e?.message || e));
      c.on(ControlEvent.DISCONNECTED, () => { if (conn === c) { conn = null; onStatus('lost', 'TikTok bağlantısı koptu'); } });
      try {
        const state = await c.connect();
        return `room ${state.roomId}`;
      } catch (err) {
        conn = null;
        const msg = String(err?.message || err);
        throw new Error(/offline|not live|isn't online|UserOffline/i.test(msg + (err?.name || '')) ? `@${username} şu an canlı yayında değil` : msg);
      }
    },
    async stop() { const c = conn; conn = null; try { await c?.disconnect(); } catch {} },
  };
}
