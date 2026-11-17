// Ortak kontrol paneli: canlı bağlantı, kurallar, deneme, istatistik, rehber. Çalışan temayı kendisi okur.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (n) => Number(n || 0).toLocaleString('vi-VN');

let ws;
let theme = null;
let rules = null;
let gifts = [];       // canlıda gerçekten görülen hediyeler
let presetGifts = []; // henüz gerçek hediye görülmediyse denemek için birkaç yaygın hediye
const send = (m) => ws?.readyState === 1 && ws.send(JSON.stringify(m));

const OV = location.origin + '/overlay';
$('ovUrl').textContent = OV;
$('copyOv').onclick = () => navigator.clipboard?.writeText(OV);
document.querySelectorAll('.origin').forEach((el) => (el.textContent = location.origin));
document.querySelectorAll('.ovlink').forEach((el) => (el.textContent = OV));
document.querySelectorAll('[data-ov]').forEach((a) => (a.href = OV + a.dataset.ov));
document.querySelectorAll('[data-copy-prompt]').forEach((b) => (b.onclick = () => {
  navigator.clipboard?.writeText(b.previousElementSibling.textContent);
  b.textContent = 'Kopyalandı ✓';
  setTimeout(() => (b.textContent = 'Kopyala'), 2000);
}));

// ---------- Tab ----------
function showTab(id) {
  if (!document.querySelector(`[data-pane="${id}"]`)) id = 'live';
  document.querySelectorAll('[data-pane]').forEach((p) => (p.hidden = p.dataset.pane !== id));
  document.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === id));
  try { localStorage.setItem('kit.tab', id); } catch {}
}
$('tabs').onclick = (e) => { const b = e.target.closest('[data-tab]'); if (b) showTab(b.dataset.tab); };
let savedTab = 'live';
try { savedTab = localStorage.getItem('kit.tab') || 'live'; } catch {}
showTab(savedTab);

// ---------- Canlı bağlantı ----------
$('btnConnect').onclick = () => send({ type: 'connect', username: $('user').value, provider: $('provider').value });
$('btnStop').onclick = () => send({ type: 'disconnect' });
$('themeSel').onchange = () => send({ type: 'setTheme', id: $('themeSel').value });
$('btnReset').onclick = () => { if (confirm('Yeni oturum başlatılsın mı? Bu oturumun sıralaması ve sayıları sıfırlanır (gerekirse önce CSV indirin).')) send({ type: 'reset' }); };
$('btnPeriodic').onclick = () => send({ type: 'periodicNow' });

const STATE_LABEL = { idle: 'Bağlı değil', connecting: 'Bağlanıyor…', reconnecting: 'Yeniden deneniyor…', connected: 'Bağlandı' };
const PROVIDER_LABEL = { tikfinity: 'TikFinity', connector: 'doğrudan' };

function renderState(s) {
  const live = s.live || {};
  const label = (STATE_LABEL[live.state] || live.state) + (live.provider ? ` · ${PROVIDER_LABEL[live.provider] || live.provider}` : '');
  $('dot').className = $('dotTop').className = 'dot ' + (live.state || 'idle');
  $('statusText').textContent = label + (live.message ? ` · ${live.message}` : '');
  $('statusTop').textContent = label + (s.demo ? ' · otomatik çalışıyor' : '');
  $('lastEv').textContent = s.lastEventAgo != null ? `· son olay ${Math.round(s.lastEventAgo / 1000)} sn önce` : '';
  const t = s.totals || {};
  $('stats').innerHTML = $('stats2').innerHTML = [['İzleyen', s.viewers], ['Sahaya giren', t.joins], ['Kalp', t.likes], ['Jeton', t.coins], ['Hediye sayısı', t.gifts], ['Yorum', t.chats], ['Takip', t.follows]]
    .map(([k, v]) => `<div><b>${fmt(v)}</b>${k}</div>`).join('');
  const row = (p) => `<li>${esc(p.name)}<span class="t">${esc(p.title)}</span><span class="c">${fmt(p.coins)}</span></li>`;
  const empty = '<span class="muted">Henüz hediye gönderen yok</span>';
  $('top').innerHTML = (s.top || []).map(row).join('') || empty;
  $('topMini').innerHTML = (s.top || []).slice(0, 3).map(row).join('') || empty;
  $('goals').innerHTML = (s.goals || []).map((g) => `<div class="goal">${esc(g.label)}: ${fmt(g.value)} / ${fmt(g.target)}<div class="bar"><div style="width:${Math.round(g.progress * 100)}%"></div></div></div>`).join('') || '<span class="muted">Temada hedef tanımlı değil</span>';
  if (!s.demo) document.querySelectorAll('[data-rate]').forEach((b) => b.classList.toggle('on', b.dataset.rate === '0'));
}

// ---------- Deneme ----------
const SIMS = [
  ['+1 kişi girdi', { kind: 'member' }], ['Yorum', { kind: 'chat' }], ['Kalp bırak', { kind: 'like' }],
  ['Takip', { kind: 'follow' }], ['Paylaş', { kind: 'share' }], ['Kombo 1 jeton ×10', { kind: 'gift', arg: 1, arg2: 10 }],
];
$('simRow').innerHTML = SIMS.map(([label], i) => `<button data-sim="${i}">${label}</button>`).join('');
$('simRow').onclick = (e) => { const sim = SIMS[e.target.dataset.sim]?.[1]; if (sim) send({ type: 'sim', ...sim }); };
document.querySelectorAll('[data-crowd]').forEach((b) => (b.onclick = () => send({ type: 'crowd', n: Number(b.dataset.crowd) })));
$('btnVoice').onclick = () => send({ type: 'testVoice', text: $('voiceText').value });
document.querySelectorAll('[data-rate]').forEach((b) => b.onclick = () => {
  document.querySelectorAll('[data-rate]').forEach((x) => x.classList.toggle('on', x === b));
  send({ type: 'demo', rate: Number(b.dataset.rate) });
});

function renderActions() {
  $('actionRow').innerHTML = theme.actions.map((a) => `<button data-action="${esc(a.id)}" title="${esc(a.description || '')}">${iconHtml(a)} ${esc(a.label)}</button>`).join('')
    + '<label class="inline"><input type="checkbox" id="bigTest"> büyük hediye</label>';
  $('actionRow').onclick = (e) => { const id = e.target.closest('[data-action]')?.dataset.action; if (id) send({ type: 'test', action: id, big: $('bigTest').checked }); };
}

const giftImg = (g) => g.image ? `<img src="${esc(g.image)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : '<span class="noimg">🎁</span>';
const GROUPS = [['Küçük hediye', 1, 9, 1], ['Orta hediye', 10, 99, 50], ['Büyük hediye', 100, Infinity, 500]]; // ad, en az, en çok, "herhangi hediye" düğmesinin fiyatı

function renderGiftTests() {
  const all = new Map();
  for (const g of [...presetGifts, ...gifts]) all.set(g.id, g);
  const list = [...all.values()].sort((a, b) => a.coins - b.coins || a.name.localeCompare(b.name));
  $('giftTests').innerHTML = GROUPS.map(([label, lo, hi, any]) => {
    const items = list.filter((g) => g.coins >= lo && g.coins <= hi);
    return `<h3>${label} <span class="muted">· ${hi === Infinity ? `${lo}+` : `${lo}–${hi}`} jeton</span></h3><div class="gifts">`
      + items.map((g) => `<button class="gift" data-gtest="${esc(g.id)}">${giftImg(g)}<span>${esc(g.name)}</span><small>${fmt(g.coins)} jeton</small></button>`).join('')
      + `<button class="gift" data-gcoins="${any}"><span class="noimg">＋</span><span>Herhangi</span><small>${fmt(any)} jeton</small></button></div>`;
  }).join('');
}
$('giftTests').onclick = (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.gcoins) return send({ type: 'sim', kind: 'gift', arg: Number(b.dataset.gcoins) });
  const g = [...gifts, ...presetGifts].find((x) => x.id === b.dataset.gtest);
  if (g) send({ type: 'sim', kind: 'gift', arg: g.coins, gift: { id: g.id, name: g.name, coins: g.coins, image: g.image || '' } });
};

// ---------- Kurallar ----------
// eylemin simgesi emoji veya temanın görsel yolu olabilir
const isImg = (icon) => /[./]/.test(icon || '');
const iconText = (a) => (a.icon && !isImg(a.icon) ? a.icon + ' ' : '');
const iconHtml = (a) => (isImg(a.icon) ? `<img class="ico" src="/themes/${esc(theme.id)}/${esc(a.icon)}" alt="">` : esc(a.icon || ''));
const actionOptions = (sel) => theme.actions.map((a) => `<option value="${esc(a.id)}"${a.id === sel ? ' selected' : ''}>${iconText(a)}${esc(a.label)}</option>`).join('');
const tail = '<td class="act"><button class="ghost sm" data-try title="Bu satırın efektini göster">▶</button><button class="ghost sm" data-del title="Satırı sil">✕</button></td>';

function rowTier(t = {}) { return `<tr><td class="n"><input type="number" min="1" data-k="minCoins" value="${t.minCoins || 1}"></td><td><select data-k="action">${actionOptions(t.action)}</select></td><td><input data-k="label" value="${esc(t.label)}"></td>${tail}</tr>`; }
function rowOverride(o = {}) { return `<tr><td class="n"><input data-k="giftId" value="${esc(o.giftId)}"></td><td><input data-k="names" value="${esc((o.names || []).join(', '))}"></td><td><select data-k="action">${actionOptions(o.action)}</select></td><td><input data-k="label" value="${esc(o.label)}"></td>${tail}</tr>`; }
function rowCommand(c = {}) {
  return `<tr><td><input data-k="keywords" value="${esc((c.keywords || []).join(', '))}"></td><td><select data-k="match"><option value="exact"${c.match !== 'contains' ? ' selected' : ''}>tam eşleşme</option><option value="contains"${c.match === 'contains' ? ' selected' : ''}>içeriyorsa</option></select></td><td><select data-k="action">${actionOptions(c.action)}</select></td><td><input data-k="label" value="${esc(c.label)}"></td><td class="n"><input type="number" min="0" data-k="cooldown" value="${Math.round((c.cooldownMs || 0) / 1000)}"></td>${tail}</tr>`;
}

function renderRules() {
  $('joinMode').value = rules.joinMode;
  $('joinKeywords').value = rules.joinKeywords.join(', ');
  $('bigGiftCoins').value = rules.bigGiftCoins;
  $('tiers').innerHTML = rules.giftTiers.map(rowTier).join('');
  $('overrides').innerHTML = rules.giftOverrides.map(rowOverride).join('');
  $('commands').innerHTML = rules.chatCommands.map(rowCommand).join('');
  renderCatalog();
}

function renderCatalog() {
  if (!gifts.length) { $('catalog').innerHTML = '<p class="muted">Henüz gerçek hediye görülmedi. Bir canlıya bağlanın; izleyicilerin gönderdiği hediyeler görsel, ad ve fiyatla burada kendiliğinden görünür.</p>'; return; }
  const used = new Set(rowsOf('overrides').map((r) => r.giftId));
  $('catalog').innerHTML = gifts.map((g) => `<button class="gift${used.has(g.id) ? ' used' : ''}" data-gift="${esc(g.id)}" title="ID ${esc(g.id)}">${giftImg(g)}<span>${esc(g.name)}</span><small>${fmt(g.coins)} jeton${used.has(g.id) ? ' · kuralı var' : ''}</small></button>`).join('');
}
$('catalog').onclick = (e) => {
  const g = gifts.find((x) => x.id === e.target.closest('[data-gift]')?.dataset.gift);
  if (!g) return;
  const row = [...$('overrides').querySelectorAll('tr')].find((tr) => tr.querySelector('[data-k="giftId"]').value === g.id);
  if (row) { row.querySelector('select').focus(); return; }
  $('overrides').insertAdjacentHTML('beforeend', rowOverride({ giftId: g.id, names: [g.name], action: theme.actions[0]?.id, label: g.name }));
  $('overrides').lastElementChild.querySelector('select').focus();
  renderCatalog();
  $('rulesMsg').textContent = `${g.name} için satır eklendi: eylemi seçin ve Kuralları kaydet'e basın.`;
};

const rowData = (tr) => Object.fromEntries([...tr.querySelectorAll('[data-k]')].map((el) => [el.dataset.k, el.value]));
const rowsOf = (id) => [...$(id).querySelectorAll('tr')].map(rowData);

function collectRules() {
  return {
    joinMode: $('joinMode').value,
    joinKeywords: $('joinKeywords').value,
    bigGiftCoins: Number($('bigGiftCoins').value),
    giftTiers: rowsOf('tiers').map((r) => ({ ...r, minCoins: Number(r.minCoins) })),
    giftOverrides: rowsOf('overrides'),
    chatCommands: rowsOf('commands').map((r) => ({ ...r, cooldownMs: Number(r.cooldown) * 1000 })),
  };
}

document.addEventListener('click', (e) => {
  if (e.target.matches('[data-del]')) { e.target.closest('tr').remove(); renderCatalog(); return; }
  if (!e.target.matches('[data-try]')) return;
  // Düzenlenen satırı dener (kaydetmek gerekmez): satırın eylemini hediye adı / yazısıyla doğrudan tetikler
  const r = rowData(e.target.closest('tr'));
  const g = gifts.find((x) => x.id === r.giftId);
  const coins = Number(r.minCoins) || g?.coins || 1;
  send({ type: 'test', action: r.action, label: r.label, giftName: g?.name || (r.names || '').split(',')[0].trim() || undefined, giftImage: g?.image, coins, big: coins >= Number($('bigGiftCoins').value) });
});
$('addTier').onclick = () => $('tiers').insertAdjacentHTML('beforeend', rowTier({ action: theme.actions[0]?.id }));
$('addOverride').onclick = () => $('overrides').insertAdjacentHTML('beforeend', rowOverride({ action: theme.actions[0]?.id }));
$('addCommand').onclick = () => $('commands').insertAdjacentHTML('beforeend', rowCommand({ action: theme.actions[0]?.id }));
$('overrides').addEventListener('change', renderCatalog);
$('saveRules').onclick = () => { send({ type: 'saveRules', rules: collectRules() }); $('rulesMsg').textContent = 'Kaydedildi ✓'; };
$('resetRules').onclick = () => { if (confirm('Düzenlenen kurallar atılsın, temanın varsayılan kuralları kullanılsın mı?')) send({ type: 'resetRules' }); };

// ---------- Tema ayarları ----------
function renderSettings(values, keepFocus = false) {
  const fields = theme.settings || [];
  $('settingsBox').hidden = !fields.length;
  if (keepFocus && $('settings').contains(document.activeElement)) return;
  $('settings').innerHTML = fields.map((f) => {
    const v = values[f.id];
    if (f.type === 'toggle') return `<label class="inline"><input type="checkbox" data-set="${esc(f.id)}"${v ? ' checked' : ''}> ${esc(f.label)}</label>`;
    if (f.type === 'select') return `<label>${esc(f.label)}<select data-set="${esc(f.id)}">${(f.options || []).map((o) => `<option value="${esc(o.value)}"${o.value === v ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select></label>`;
    if (f.type === 'range') return `<label>${esc(f.label)} <output>${v}</output><input type="range" data-set="${esc(f.id)}" min="${f.min ?? 0}" max="${f.max ?? 100}" step="${f.step ?? 1}" value="${v}"></label>`;
    return `<label>${esc(f.label)}<input data-set="${esc(f.id)}" value="${esc(v)}"></label>`;
  }).join('');
}
let settingsTimer;
$('settings').addEventListener('input', (e) => {
  const el = e.target.closest('[data-set]');
  if (!el) return;
  if (el.type === 'range') el.previousElementSibling.textContent = el.value;
  const value = el.type === 'checkbox' ? el.checked : el.type === 'range' ? Number(el.value) : el.value;
  clearTimeout(settingsTimer);
  settingsTimer = setTimeout(() => send({ type: 'saveSettings', values: { [el.dataset.set]: value } }), 150);
});

// ---------- Günlük ----------
function log(text) {
  const el = document.createElement('div');
  el.textContent = new Date().toLocaleTimeString('vi-VN') + '  ' + text;
  $('log').prepend(el);
  while ($('log').children.length > 300) $('log').lastChild.remove();
}
function describe(ev) {
  const n = ev.user?.name || '';
  switch (ev.kind) {
    case 'join': return `${n} sahaya girdi`;
    case 'chat': return `${n}: ${ev.text}`;
    case 'gift': return `${ev.test ? '[deneme] ' : ''}${n} ${ev.gift?.name} ×${ev.count} gönderdi (${ev.total} jeton) → ${ev.label}${ev.big ? ' · BÜYÜK HEDİYE' : ''}`;
    case 'command': return `${n} "${ev.text}" komutunu yazdı → ${ev.label || ev.action}`;
    case 'follow': return `${n} takip etti`;
    case 'share': return `${n} paylaştı`;
    case 'title': return `${n} ${ev.title} unvanına ulaştı`;
    case 'goal': return `🎯 Hedefe ulaşıldı ${ev.label}: ${fmt(ev.value)}`;
    case 'streamEnd': return 'Canlı yayın sona erdi';
    default: return null;
  }
}

// ---------- WebSocket ----------
function connect() {
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onopen = () => send({ type: 'hello', role: 'control' });
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === 'init') {
      const changed = theme && theme.id !== msg.theme.id;
      theme = msg.theme; rules = msg.rules; gifts = msg.gifts || []; presetGifts = msg.presetGifts || [];
      document.title = `${theme.name} · TikTok Live Kit`;
      document.querySelectorAll('[data-starter]').forEach((el) => (el.hidden = !theme.id.startsWith('template'))); // boş şablon: kendi temanızı yapmayı önerir
      $('themeSel').innerHTML = msg.themes.map((t) => `<option value="${esc(t.id)}"${t.id === theme.id ? ' selected' : ''}>${esc(t.name)}</option>`).join('');
      $('provider').value = msg.config.provider;
      if (!$('user').value) $('user').value = msg.config.tiktokUsername;
      renderActions(); renderRules(); renderGiftTests(); renderState(msg.state); renderSettings(msg.settings || {});
      if (changed) setTimeout(() => ($('preview').src = '/overlay?quiet&mute'), 300);
    } else if (msg.type === 'state') renderState(msg);
    else if (msg.type === 'rules') { rules = msg.rules; renderRules(); }
    else if (msg.type === 'settings') renderSettings(msg.values, true);
    else if (msg.type === 'gifts') { gifts = msg.gifts; renderCatalog(); renderGiftTests(); log('Yeni hediye görüldü, hediye kitaplığına eklendi'); }
    else if (msg.type === 'event' && msg.ev.kind !== 'like') { const t = describe(msg.ev); if (t) log(t); }
    else if (msg.type === 'error') log('Hata: ' + msg.message);
  };
  ws.onclose = () => { $('statusText').textContent = $('statusTop').textContent = 'Sunucu bağlantısı koptu, yeniden bağlanılıyor…'; $('dot').className = $('dotTop').className = 'dot'; setTimeout(connect, 1500); };
}
connect();
