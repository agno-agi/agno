// Live SDK cho theme: kết nối lõi, tự nối lại, co khung, phát sự kiện. Theme chỉ cần Live.on(...).
//
//   Live.on('ready',    ({ theme, players, state }) => {})  // lúc nối (và nối lại): dựng lại đám đông có sẵn
//   Live.on('join',     (e) => {})   e.user = { id, name, avatar, title, coins, rank, isPlayer }
//   Live.on('chat',     (e) => {})   e.text
//   Live.on('like',     (e) => {})   e.count
//   Live.on('gift',     (e) => {})   e.action, e.label, e.gift{name,image,coins}, e.count, e.total, e.big, e.combo
//   Live.on('command',  (e) => {})   lệnh chat đã khớp luật: e.action
//   Live.on('follow' | 'share' | 'title' | 'goal' | 'streamEnd', (e) => {})
//   Live.on('state',    (s) => {})   s.viewers, s.totals, s.top, s.goals
//   Live.on('reset',    () => {})    bảng điều khiển bấm "Phiên mới"
//   Live.on('settings', (v) => {})   cài đặt riêng của theme (khai báo "settings" trong theme.json) vừa đổi
//   Live.on('*',        (e) => {})   mọi sự kiện
//
//   Live.stage(el)      co phần tử el (kích thước gốc theo theme) vừa cửa sổ, giữ tỉ lệ
//   Live.sound(url, vol) phát âm thanh (tự giới hạn số tiếng cùng lúc)
//   Live.img(url)       ảnh có cache, bỏ referrer để ảnh TikTok tải được
//   Live.audio()        AudioContext dùng chung (null khi tắt tiếng); Live.muted = true ở khung xem trước (?mute)
//   Live.settings       giá trị cài đặt hiện tại của theme

(function () {
  const handlers = {};
  const Live = {
    theme: null,
    state: null,
    settings: {},
    muted: new URLSearchParams(location.search).has('mute'),
    connected: false,
    on(kind, fn) { (handlers[kind] ||= []).push(fn); return Live; },
    emit(kind, data) {
      for (const fn of handlers[kind] || []) try { fn(data); } catch (e) { console.error(`[Live] lỗi trong handler "${kind}"`, e); }
      if (kind !== 'state' && kind !== 'ready') for (const fn of handlers['*'] || []) try { fn(data); } catch (e) { console.error(e); }
    },
  };

  // ---------- Kết nối ----------
  let retry = 500;
  function connect() {
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onopen = () => { retry = 500; ws.send(JSON.stringify({ type: 'hello', role: 'overlay' })); };
    ws.onmessage = (m) => {
      let msg;
      try { msg = JSON.parse(m.data); } catch { return; }
      if (msg.type === 'init') {
        Live.theme = msg.theme;
        Live.state = msg.state;
        Live.settings = msg.settings || {};
        Live.connected = true;
        banner(false);
        Live.emit('ready', { theme: msg.theme, players: msg.players || [], state: msg.state, guide: msg.guide });
        Live.emit('state', msg.state);
      } else if (msg.type === 'event') Live.emit(msg.ev.kind, msg.ev);
      else if (msg.type === 'state') { Live.state = msg; Live.emit('state', msg); }
      else if (msg.type === 'reset') Live.emit('reset', {});
      else if (msg.type === 'guide') Live.emit('guide', msg);
      else if (msg.type === 'settings') { Live.settings = msg.values || {}; Live.emit('settings', Live.settings); }
      else if (msg.type === 'reload') location.reload();
    };
    ws.onclose = () => {
      Live.connected = false;
      banner(true);
      setTimeout(connect, retry);
      retry = Math.min(5000, retry * 2);
    };
  }

  // Báo mất kết nối (ẩn được bằng ?quiet)
  let bannerEl = null;
  function banner(show) {
    if (new URLSearchParams(location.search).has('quiet')) return;
    if (!bannerEl) {
      bannerEl = document.createElement('div');
      bannerEl.textContent = 'Mất kết nối server, đang nối lại…';
      bannerEl.style.cssText = 'position:fixed;top:8px;left:8px;z-index:99999;padding:4px 10px;border-radius:6px;background:rgba(170,30,30,.9);color:#fff;font:14px system-ui;display:none';
      document.addEventListener('DOMContentLoaded', () => document.body.appendChild(bannerEl));
      if (document.body) document.body.appendChild(bannerEl);
    }
    bannerEl.style.display = show ? 'block' : 'none';
  }

  // ---------- Co khung ----------
  Live.stage = function (el, w, h) {
    const W = w || Live.theme?.width || el.offsetWidth || 1080;
    const H = h || Live.theme?.height || el.offsetHeight || 1920;
    Object.assign(el.style, { position: 'absolute', left: '0', top: '0', width: W + 'px', height: H + 'px', transformOrigin: '0 0' });
    const fit = () => {
      const s = Math.min(innerWidth / W, innerHeight / H);
      el.style.left = (innerWidth - W * s) / 2 + 'px';
      el.style.top = (innerHeight - H * s) / 2 + 'px';
      el.style.transform = `scale(${s})`;
    };
    addEventListener('resize', fit);
    fit();
    return fit;
  };

  // ---------- Ảnh, âm thanh ----------
  const imgs = new Map();
  Live.img = function (url) {
    if (!url) return null;
    if (imgs.has(url)) return imgs.get(url);
    const im = new Image();
    im.referrerPolicy = 'no-referrer';
    im.crossOrigin = 'anonymous';
    im.onerror = () => { if (im.crossOrigin) { im.crossOrigin = null; im.src = url; } };
    im.src = url;
    imgs.set(url, im);
    if (imgs.size > 800) imgs.delete(imgs.keys().next().value);
    return im;
  };

  let ctx = null;
  Live.audio = function () {
    if (Live.muted) return null;
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
      // trình duyệt thường chặn âm thanh tới khi có thao tác; OBS thì không chặn
      const unlock = () => ctx.state === 'suspended' && ctx.resume();
      addEventListener('pointerdown', unlock);
      addEventListener('keydown', unlock);
    }
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    return ctx;
  };

  let playing = 0;
  Live.sound = function (url, volume = 0.8) {
    if (!url || playing >= 4 || Live.muted) return;
    const a = new Audio(url);
    a.volume = volume;
    playing++;
    a.onended = a.onerror = () => { playing--; };
    a.play().catch(() => { playing--; });
  };

  window.Live = Live;
  connect();
})();
