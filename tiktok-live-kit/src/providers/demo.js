// Henüz canlı değilken temayı denemek için sahte izleyiciler (Test Lab). Gerçek canlıyla aynı işlem hattından geçer.

const NAMES = ['Ayşe K.', 'Mehmet Y.', 'zeynep_44', 'Hasan', 'Fatma H.', 'ali.can', 'Emre', 'Elif Nur', 'Mustafa', 'Hatice', 'Yusuf', 'Merve', 'Kemal A.', 'Selin', 'Ömer', 'Gülşen', 'Burak', 'Esra', 'İbrahim', 'Rabia'];
const CHATS = ['Allah rahmet eylesin', 'Mekanı cennet olsun', '🤲🤲🤲', 'Başımız sağolsun', 'Ailesine sabır diliyorum', 'Amin', 'Nur içinde yatsın', 'Selamün aleyküm'];
const GIFTS = [
  { id: '5655', name: 'Rose', unitCoins: 1 },
  { id: '5487', name: 'Finger Heart', unitCoins: 5 },
  { id: '8913', name: 'Rosa', unitCoins: 10 },
  { id: '6064', name: 'GG', unitCoins: 1 },
  { id: '5585', name: 'Confetti', unitCoins: 100 },
  { id: '7934', name: 'Heart Me', unitCoins: 1 },
];

const pick = (a) => a[Math.floor(Math.random() * a.length)];

export function createDemo({ onEvent, extraChats = [] }) {
  let seq = 0;
  let timer = null;
  const known = [];

  const newUser = () => {
    const i = seq++;
    const u = { id: 'demo' + i, uniqueId: 'demo' + i, name: i < NAMES.length ? NAMES[i] : `${pick(NAMES)} ${i}`, avatar: '' };
    known.push(u);
    if (known.length > 400) known.shift();
    return u;
  };
  const someone = () => (known.length && Math.random() < 0.85 ? pick(known) : newUser());

  const make = {
    member: () => ({ kind: 'member', user: newUser() }),
    chat: (text) => ({ kind: 'chat', user: someone(), text: text || pick([...CHATS, ...extraChats]) }),
    like: (n) => ({ kind: 'like', user: someone(), likeCount: n || 1 + Math.floor(Math.random() * 15) }),
    follow: () => ({ kind: 'follow', user: someone() }),
    share: () => ({ kind: 'share', user: someone() }),
    // gift: belirli bir hediye (görülen hediye kataloğundan); ID / ada göre kuralı doğru denemek için
    gift: (coins, count = 1, gift) => {
      const g = gift?.id ? { id: String(gift.id), name: String(gift.name || 'Hediye'), unitCoins: Number(gift.coins) || Number(coins) || 1, image: String(gift.image || '') }
        : GIFTS.find((x) => x.unitCoins === Number(coins)) || { id: 'demo-' + coins, name: `Hediye ${coins} jeton`, unitCoins: Number(coins) || 1 };
      return { kind: 'gift', user: someone(), gift: { image: '', ...g, streakable: false, repeatCount: Number(count) || 1, repeatEnd: true, groupId: '' } };
    },
  };

  function fire(kind, arg, arg2, arg3) {
    const ev = make[kind]?.(arg, arg2, arg3);
    if (ev) onEvent(ev);
  }

  // n kişiyi sahaya bırakır (eşit aralıkla, motorun maxJoinsPerSecond sınırının altında ki atılmasınlar) kalabalık sahneyi denemek için
  function crowd(n, perSecond = 12) {
    const total = Math.max(1, Math.min(500, Math.round(Number(n) || 0)));
    const gap = Math.max(4000 / total, 1000 / Math.max(1, perSecond));
    for (let i = 0; i < total; i++) setTimeout(() => fire('member'), Math.round(i * gap));
  }

  // gifts: false → gerçek yayındayken yalnızca giriş, sohbet, kalp üretilir; izleyicinin önüne sahte hediye konmaz
  function auto(rate = 1, { gifts = true } = {}) {
    stop();
    if (!rate) return;
    timer = setInterval(() => {
      const r = Math.random();
      if (r < 0.25) fire('member');
      else if (r < 0.5) fire('chat');
      else if (r < 0.8 || !gifts) fire('like');
      else if (r < 0.83) fire('follow');
      else fire('gift', pick([1, 1, 1, 1, 5, 5, 10, 100]));
    }, Math.max(80, 700 / rate));
  }

  function stop() { clearInterval(timer); timer = null; }

  return { fire, crowd, auto, stop, get running() { return Boolean(timer); }, gifts: GIFTS };
}
