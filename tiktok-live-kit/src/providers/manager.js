// Quản lý kết nối live: chọn nguồn, tự thử lại (giãn dần 2s → 30s), tự chuyển nguồn khi chế độ "auto",
// và canh "im lặng bất thường" (đang kết nối mà lâu không có sự kiện nào thì nối lại).

import { createTikFinity } from './tikfinity.js';
import { createConnector } from './connector.js';

export function createManager({ config, onEvent, onStatus, lastEventAt }) {
  let active = null;
  let wanted = null; // { username, provider }
  let failures = 0;
  let retryTimer = null;
  let attempt = 0;
  let connectedAt = 0;
  const status = { state: 'idle', provider: null, username: '', message: '' };

  const set = (state, message = '', provider = status.provider) => {
    Object.assign(status, { state, message, provider, username: wanted?.username || '' });
    console.log(`[live] ${state}${provider ? ' (' + provider + ')' : ''}${message ? ': ' + message : ''}`);
    onStatus({ ...status });
  };

  const order = (p) => (p === 'tikfinity' ? ['tikfinity'] : p === 'connector' ? ['connector'] : ['tikfinity', 'connector']);

  function build(name, my) {
    const common = {
      onEvent: (ev) => { if (my === attempt) onEvent(ev); },
      onStatus: (state, msg) => { if (my === attempt && state === 'lost') { active = null; retry(msg); } },
    };
    return name === 'tikfinity'
      ? createTikFinity({ url: config.tikfinityUrl, ...common })
      : createConnector({ username: wanted.username, signApiKey: config.signApiKey || process.env.EULER_API_KEY, ...common });
  }

  async function connect(username, provider = config.provider || 'auto') {
    await stop(true);
    wanted = { username: String(username || '').replace(/^@/, '').trim(), provider };
    failures = 0;
    return tryConnect();
  }

  async function tryConnect() {
    clearTimeout(retryTimer);
    const my = ++attempt;
    const errors = [];
    for (const name of order(wanted.provider)) {
      if (name === 'connector' && !wanted.username) { errors.push('connector: kanal adı girilmedi'); continue; }
      set(failures ? 'reconnecting' : 'connecting', '', name);
      const p = build(name, my);
      try {
        const info = await p.start();
        if (my !== attempt) { await p.stop(); return; }
        active = p;
        failures = 0;
        connectedAt = Date.now();
        set('connected', [wanted.username && '@' + wanted.username, info].filter(Boolean).join(' · '), name);
        return;
      } catch (err) {
        await p.stop();
        if (my !== attempt) return;
        errors.push(`${name}: ${err.message}`);
      }
    }
    retry(errors.join(' | '));
  }

  function retry(reason) {
    if (!wanted) return;
    const delay = Math.min(30000, 2000 * 2 ** Math.min(failures, 4));
    failures += 1;
    set('reconnecting', `${reason} · ${Math.round(delay / 1000)} sn sonra tekrar denenecek`);
    clearTimeout(retryTimer);
    retryTimer = setTimeout(() => { if (wanted) tryConnect(); }, delay);
  }

  async function stop(keep = false) {
    clearTimeout(retryTimer);
    attempt++;
    const p = active;
    active = null;
    if (!keep) wanted = null;
    await p?.stop();
    if (!keep) set('idle', '', null);
  }

  // Canh im lặng: nguồn trực tiếp đôi khi "treo" mà không báo ngắt
  const watchdog = setInterval(() => {
    if (!active || status.state !== 'connected' || active.name !== 'connector') return;
    const quietMs = Date.now() - Math.max(lastEventAt(), connectedAt);
    if (quietMs > (config.watchdogSeconds || 180) * 1000) { console.warn('[live] uzun süre olay gelmedi, yeniden bağlanılıyor'); active.stop(); active = null; retry('Olay alınamadı'); }
  }, 15000);
  watchdog.unref();

  return { connect, stop, get status() { return { ...status }; } };
}
