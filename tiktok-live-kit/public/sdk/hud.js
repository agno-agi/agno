// Kit.hud: giao diện có sẵn trên overlay. Bật / tắt và đổi chữ trong theme.json "hud", đổi màu trong "colors".
//   "hud": {
//     "title":   { "text": "Tên kênh", "sub": "Dòng phụ" },      tiêu đề trên cùng
//     "counters": true,                                         số người trong cảnh, người xem, tim, đồng hồ phiên
//     "giftCard": { "verb": "đã tặng", "unit": "xu" },          thẻ vinh danh lớn khi có quà
//     "tiers": true,                                            ô mức quà (lấy từ actions có "card")
//     "board":  { "title": "BẢNG VÀNG", "size": 3 },            bảng xếp hạng
//     "ticker": { "title": "Vừa tặng", "size": 5 },             danh sách quà vừa nhận
//     "goal": true,                                             thanh mục tiêu
//     "guide":  { "title": "Cách tham gia" },                   bảng hướng dẫn tự sinh từ luật
//     "safeTop": 150                                            chừa khoảng trên cùng cho giao diện TikTok
//   }
// Lá thăm (theme.json "draws") hiện ở khung giữa: trường "title" và "text" của lá thăm.
// Theme muốn giao diện riêng thì gán Kit.hud = { init, giftCard, ticker, state, guide, toast, periodic, draw, remember, reset } trong theme.js.

(function () {
  const K = window.Kit;
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = (n) => Number(n || 0).toLocaleString('tr-TR');
  let cfg = {}, theme = {}, root = null, startedAt = Date.now();
  const lastWords = new Map();
  const tickerItems = [];

  const STYLE = `
  .kit-hud { position:absolute; inset:0; pointer-events:none; font-family: var(--kit-font, 'Be Vietnam Pro', system-ui, sans-serif); color: var(--kit-text,#fdf3dc); }
  .kit-panel { background: var(--kit-panel, linear-gradient(180deg, rgba(40,18,6,.86), rgba(20,8,2,.9))); border: 2px solid var(--kit-border, rgba(214,168,82,.75)); border-radius: 18px; box-shadow: 0 6px 24px rgba(0,0,0,.35); }
  .kit-panel.img { background: var(--kit-panel-img) center/100% 100% no-repeat; border: 0; box-shadow:none; }
  .kit-title { position:absolute; left:50%; transform:translateX(-50%); padding:12px 40px; text-align:center; white-space:nowrap; }
  .kit-title h1 { margin:0; font-size:46px; letter-spacing:2px; color: var(--kit-accent,#ffd987); font-weight:800; }
  .kit-title p { margin:2px 0 0; font-size:24px; opacity:.85; }
  .kit-counters { position:absolute; left:50%; transform:translateX(-50%); display:flex; gap:10px; }
  .kit-counters div { padding:6px 16px; border-radius:999px; font-size:22px; font-weight:700; background: rgba(0,0,0,.45); border:1px solid var(--kit-border, rgba(214,168,82,.6)); }
  .kit-card { position:absolute; left:40px; right:40px; padding:18px 26px; text-align:center; opacity:0; transform: translateY(-14px) scale(.97); transition: opacity .35s, transform .35s; }
  .kit-card.show { opacity:1; transform:none; }
  .kit-card .who { font-size:46px; font-weight:800; color: var(--kit-accent,#ffd987); line-height:1.15; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .kit-card .what { font-size:30px; margin-top:4px; }
  .kit-card .quote { font-size:26px; font-style:italic; opacity:.9; margin-top:6px; }
  .kit-card.big { box-shadow: 0 0 60px var(--kit-glow, rgba(255,200,90,.7)); }
  .kit-side { position:absolute; width:300px; padding:14px 16px; font-size:21px; }
  .kit-side h3 { margin:0 0 8px; text-align:center; font-size:22px; letter-spacing:1px; color: var(--kit-accent,#ffd987); white-space:nowrap; }
  .kit-side ol, .kit-side ul { list-style:none; margin:0; padding:0; display:grid; gap:6px; }
  .kit-side li { display:flex; gap:8px; align-items:center; }
  .kit-side li .n { width:26px; height:26px; flex:none; border:2px solid var(--kit-border,#d6a852); border-radius:50%; display:grid; place-items:center; font-size:14px; font-weight:800; }
  .kit-side li .nm { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .kit-side li .c { color: var(--kit-accent,#ffd987); font-weight:800; }
  .kit-side li.empty { opacity:.45; }
  .kit-guide li { align-items:flex-start; line-height:1.25; }
  .kit-ticker li { animation: kitIn .5s ease-out; }
  @keyframes kitIn { from { opacity:0; transform: translateX(20px); } }
  .kit-tiers { position:absolute; left:30px; right:30px; display:grid; gap:12px; }
  .kit-tier { height:112px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; }
  .kit-tier .ico { font-size:32px; line-height:1; }
  .kit-tier .ico img { height:44px; }
  .kit-tier .coin { font-size:21px; font-weight:800; color: var(--kit-accent,#ffd987); }
  .kit-tier .lbl { font-size:23px; font-weight:700; }
  .kit-tier.hit { animation: kitHit .9s ease-out; }
  @keyframes kitHit { 0% { box-shadow: 0 0 50px var(--kit-glow, rgba(255,200,90,.9)); transform: scale(1.06); } }
  .kit-goal { position:absolute; left:30px; right:30px; }
  .kit-goal .lb { font-size:21px; font-weight:700; margin-bottom:5px; text-shadow:0 2px 4px #000; display:flex; justify-content:space-between; }
  .kit-goal .bar { height:14px; border-radius:999px; background: rgba(0,0,0,.55); border:1px solid var(--kit-border, rgba(214,168,82,.6)); overflow:hidden; }
  .kit-goal .fill { height:100%; width:0; background: linear-gradient(90deg, var(--kit-accent,#e2b25a), #fff3c4); transition: width .6s; }
  .kit-toast { position:absolute; left:40px; right:40px; text-align:center; font-size:42px; font-weight:800; color:#fff1c9; text-shadow: 0 0 18px var(--kit-glow, rgba(255,180,60,.9)), 0 2px 4px #000; opacity:0; transition: opacity .4s; }
  .kit-toast.show { opacity:1; }
  .kit-periodic { position:absolute; left:90px; right:90px; padding:20px 28px; text-align:center; opacity:0; transform: translateY(10px); transition: opacity .5s, transform .5s; }
  .kit-periodic.show { opacity:1; transform:none; }
  .kit-periodic h4 { margin:0 0 6px; color: var(--kit-accent,#ffd987); font-size:26px; letter-spacing:2px; }
  .kit-periodic p { margin:0; font-size:28px; line-height:1.45; font-style:italic; }
  .kit-unmute { position:absolute; left:50%; bottom:420px; transform:translateX(-50%); padding:14px 26px; font-size:26px; font-weight:800; pointer-events:auto; cursor:pointer; display:none; }
  `;

  function init(o) {
    theme = o.theme; cfg = theme.hud || {};
    root = document.createElement('div');
    root.className = 'kit-hud';
    o.stage.appendChild(root);
    const style = document.createElement('style'); style.textContent = STYLE; document.head.appendChild(style);
    applyColors(theme.colors || {});
    const top = cfg.safeTop ?? 150;
    let y = top;
    if (cfg.title) { root.insertAdjacentHTML('beforeend', `<div class="kit-title kit-panel" style="top:${y}px"><h1>${esc(cfg.title.text || theme.name)}</h1>${cfg.title.sub ? `<p>${esc(cfg.title.sub)}</p>` : ''}</div>`); y += cfg.title.sub ? 118 : 92; }
    if (cfg.counters) { root.insertAdjacentHTML('beforeend', `<div class="kit-counters" style="top:${y}px"><div data-c="people">👥 0</div><div data-c="viewers">👀 0</div><div data-c="likes">❤️ 0</div><div data-c="clock">⏱ 00:00</div></div>`); y += 58; }
    const cardY = cfg.giftCard?.top ?? y + 6;  // theme đặt "giftCard": { "top": 1480 } để thẻ không che vật chính (tượng, sân khấu)
    if (cfg.giftCard !== false) root.insertAdjacentHTML('beforeend', `<div class="kit-card kit-panel" style="top:${cardY}px"><div class="who"></div><div class="what"></div><div class="quote"></div></div>`);
    const sideY = cfg.sideTop ?? y + 196;
    if (cfg.guide) root.insertAdjacentHTML('beforeend', `<div class="kit-side kit-panel kit-guide" style="left:24px;top:${sideY}px"><h3>${esc(cfg.guide.title || 'Nasıl katılırım')}</h3><ul></ul></div>`);
    let rightY = sideY;
    if (cfg.board) { root.insertAdjacentHTML('beforeend', `<div class="kit-side kit-panel kit-board" style="right:24px;top:${rightY}px"><h3>${esc(cfg.board.title || 'ANMA DEFTERİ')}</h3><ol></ol></div>`); rightY += 70 + (cfg.board.size || 3) * 34; }
    if (cfg.ticker) root.insertAdjacentHTML('beforeend', `<div class="kit-side kit-panel kit-ticker" style="right:24px;top:${rightY + 12}px"><h3>${esc(cfg.ticker.title || 'Son gönderilen')}</h3><ul></ul></div>`);
    root.insertAdjacentHTML('beforeend', `<div class="kit-toast" style="top:${sideY - 20}px"></div>`);
    root.insertAdjacentHTML('beforeend', `<div class="kit-periodic kit-panel" style="top:${cfg.periodicTop ?? cardY}px"><h4></h4><p></p></div>`);
    const bottom = 30;
    if (cfg.tiers !== false) {
      const tiers = (theme.actions || []).filter((a) => a.card).slice(0, 4);
      if (tiers.length) {
        root.insertAdjacentHTML('beforeend', `<div class="kit-tiers" style="bottom:${bottom}px;grid-template-columns:repeat(${tiers.length},1fr)">${tiers.map((a) =>
          `<div class="kit-tier kit-panel" data-action="${esc(a.id)}"><div class="ico">${/\.(png|webp|gif|jpe?g|svg)$/i.test(a.icon || '') ? `<img src="${esc(a.icon)}">` : esc(a.icon || '✨')}</div><div class="coin">${esc(a.card)}</div><div class="lbl">${esc(a.label)}</div></div>`).join('')}</div>`);
      }
    }
    if (cfg.goal !== false && (theme.goals || []).length) root.insertAdjacentHTML('beforeend', `<div class="kit-goal" style="bottom:${bottom + 132}px"><div class="lb"><span class="gl"></span><span class="gv"></span></div><div class="bar"><div class="fill"></div></div></div>`);
    if (cfg.panelImage) { root.style.setProperty('--kit-panel-img', `url("${cfg.panelImage}")`); root.querySelectorAll('.kit-panel').forEach((el) => el.classList.add('img')); }
    root.insertAdjacentHTML('beforeend', `<div class="kit-unmute kit-panel">🔔 Sesi açmak için dokun</div>`);
    const un = $('.kit-unmute', root);
    un.onclick = () => { Live.audio()?.resume(); un.style.display = 'none'; K.audio.init(); };
    setTimeout(() => { const a = Live.audio(); if (a && a.state === 'suspended') un.style.display = 'block'; }, 1500);
    setInterval(tickClock, 1000);
  }

  function applyColors(c) {
    const map = { text: '--kit-text', accent: '--kit-accent', border: '--kit-border', panel: '--kit-panel', glow: '--kit-glow', font: '--kit-font' };
    for (const [k, v] of Object.entries(map)) if (c[k]) document.documentElement.style.setProperty(v, c[k]);
  }

  function tickClock() {
    const el = root && $('[data-c="clock"]', root);
    if (!el) return;
    const s = Math.floor((Date.now() - startedAt) / 1000);
    el.textContent = `⏱ ${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }

  // ---------- Thẻ vinh danh ----------
  const cardQ = [];
  let cardBusy = false;
  function giftCard(ev) {
    if (cfg.giftCard === false) return;
    cardQ.push(ev);
    if (cardQ.length > 12) cardQ.splice(0, cardQ.length - 12);
    if (!cardBusy) nextCard();
  }
  function nextCard() {
    const el = $('.kit-card', root);
    const ev = cardQ.shift();
    if (!ev || !el) { cardBusy = false; el?.classList.remove('show'); return; }
    cardBusy = true;
    const g = cfg.giftCard || {};
    const said = lastWords.get(ev.user?.id);
    $('.who', el).textContent = ev.user?.name || 'Misafir';
    $('.what', el).textContent = `${g.verb || 'gönderdi:'} ${ev.gift?.name || ev.label}${ev.count > 1 ? ` ×${ev.count}` : ''}${ev.total ? ` · ${g.unit || 'jeton'} ${fmt(ev.total)}` : ''}`;
    $('.quote', el).textContent = said && Date.now() - said.at < 120000 ? `“${said.text}”` : ev.label ? `✦ ${ev.label} ✦` : '';
    el.classList.toggle('big', Boolean(ev.big));
    el.classList.remove('show'); void el.offsetWidth; el.classList.add('show');
    const tier = root.querySelector(`.kit-tier[data-action="${CSS.escape(ev.action || '')}"]`);
    if (tier) { tier.classList.remove('hit'); void tier.offsetWidth; tier.classList.add('hit'); }
    setTimeout(() => { el.classList.remove('show'); setTimeout(nextCard, 350); }, cardQ.length > 4 ? 1400 : ev.big ? 4500 : 3000);
  }

  function ticker(ev) {
    const ul = root && $('.kit-ticker ul', root);
    if (!ul) return;
    tickerItems.unshift(ev);
    tickerItems.length = Math.min(tickerItems.length, cfg.ticker.size || 5);
    ul.innerHTML = tickerItems.map((e) => `<li><span class="nm">${esc(e.user?.name)}</span><span class="c">${esc(e.label || e.gift?.name)}${e.count > 1 ? ' ×' + e.count : ''}</span></li>`).join('');
  }

  // ---------- Trạng thái ----------
  function state(s, peopleCount) {
    if (!root) return;
    const set = (k, v) => { const el = $(`[data-c="${k}"]`, root); if (el) el.textContent = v; };
    set('people', `👥 ${fmt(peopleCount)}`);
    set('viewers', `👀 ${fmt(s.viewers)}`);
    set('likes', `❤️ ${fmt(s.totals?.likes)}`);
    const ol = $('.kit-board ol', root);
    if (ol) {
      const n = cfg.board.size || 3;
      ol.innerHTML = Array.from({ length: n }, (_, i) => {
        const d = (s.top || [])[i];
        return d ? `<li><span class="n">${i + 1}</span><span class="nm">${esc(d.name)}</span><span class="c">${fmt(d.coins)}</span></li>` : `<li class="empty"><span class="n">${i + 1}</span><span class="nm">—</span></li>`;
      }).join('');
    }
    const g = (s.goals || [])[0], ge = $('.kit-goal', root);
    if (g && ge) { $('.gl', ge).textContent = g.label; $('.gv', ge).textContent = `${fmt(g.value)} / ${fmt(g.target)}`; $('.fill', ge).style.width = `${Math.round(g.progress * 100)}%`; }
  }

  // ---------- Bảng hướng dẫn tự sinh từ luật ----------
  function guide(data, chars) {
    const ul = root && $('.kit-guide ul', root);
    if (!ul || !data?.rules) return;
    const r = data.rules, lines = [];
    lines.push(r.joinMode === 'keyword' && r.joinKeywords?.length ? `💬 "${r.joinKeywords[0]}" yazarak katıl` : '💬 Yorum yaz veya kalp bırak');
    for (const o of r.giftOverrides || []) {
      const g = (data.gifts || []).find((x) => x.id === o.giftId);
      const name = g?.name || o.names?.[0];
      if (name) lines.push(`🎁 ${name}: ${o.label || o.action}`);
    }
    for (const t of r.giftTiers || []) lines.push(`🎁 ${t.minCoins}+ jeton: ${t.label || t.action}`);
    for (const c of r.chatCommands || []) lines.push(`💬 "${c.keywords[0]}" yaz: ${c.label || c.action}`);
    const kws = (chars || []).map((c) => c.keywords?.[0]).filter(Boolean);
    if (kws.length > 1) lines.push(`🎭 ${kws.slice(0, 6).map((k) => `"${k}"`).join(' · ')} yazarak görünümü değiştir`);
    ul.innerHTML = lines.slice(0, cfg.guide.max || 7).map((l) => `<li>${esc(l)}</li>`).join('');
  }

  let toastTimer = null;
  function toast(text, ms = 3500) {
    const el = root && $('.kit-toast', root);
    if (!el) return;
    el.textContent = text; el.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), ms);
  }

  let periodicTimer = null;
  function periodic(ev) {
    const el = root && $('.kit-periodic', root);
    if (!el || !ev.text) return;
    $('h4', el).textContent = ev.title || '';
    $('p', el).textContent = ev.text;
    el.classList.add('show');
    clearTimeout(periodicTimer); periodicTimer = setTimeout(() => el.classList.remove('show'), 12000);
  }

  function draw(ev) {
    const d = ev.draw || {};
    const text = [d.title, ...[].concat(d.text || [])].filter(Boolean).join(' · ') || `No ${d.n}`;
    periodic({ title: `${ev.user?.name || ''} · ${ev.label || 'Dilek'}`, text });
  }

  function remember(userId, text) { const t = String(text || '').trim(); if (t.length >= 6) lastWords.set(userId, { text: t.slice(0, 90), at: Date.now() }); }
  function reset() { startedAt = Date.now(); tickerItems.length = 0; cardQ.length = 0; const ul = root && $('.kit-ticker ul', root); if (ul) ul.innerHTML = ''; }

  K.hud = { init, giftCard, ticker, state, guide, toast, periodic, draw, remember, reset };
})();
