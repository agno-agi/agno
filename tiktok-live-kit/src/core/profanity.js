// Küfür filtresi (Türkçe + yaygın İngilizce). İsimler ve sohbet metni bu süzgeçten geçer.
// Yöntem: metni sadeleştir (küçük harf, Türkçe harfler → ASCII, leet rakamlar, tekrar eden harfler, harf aralarındaki
// ayraçlar) ve KELİME BAŞINDAN eşleştir; "şikayet", "sikke" gibi masum kelimeler eşleşmez.
// Liste eksiksiz değildir: theme.json "filter.extraWords" ile genişletilir, canlıda yeni biri çıkarsa oraya eklenir.

const TR_MAP = { ı: 'i', İ: 'i', ş: 's', Ş: 's', ç: 'c', Ç: 'c', ğ: 'g', Ğ: 'g', ö: 'o', Ö: 'o', ü: 'u', Ü: 'u', â: 'a', î: 'i', û: 'u' };
const LEET = { 0: 'o', 1: 'i', 3: 'e', 4: 'a', 5: 's', 7: 't', '@': 'a', $: 's' };

/** Karşılaştırma için sadeleştirir: küçük harf, Türkçe harfler → ASCII, leet rakamlar (s1kt1r → siktir). */
export function squash(s) {
  let t = String(s || '').replace(/[ıİşŞçÇğĞöÖüÜâîû]/g, (c) => TR_MAP[c]).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  t = t.replace(/[013457@$]/g, (c) => LEET[c] ?? c);
  return t;
}
const words = (s) => squash(s).replace(/[^a-z]+/g, ' ').replace(/(.)\1+/g, '$1').trim().split(' ').filter(Boolean);
// Tek harflerin arası ayrılmış yazım ("s i k t i r", "o.r.o.s.p.u") birleştirilir
const joinSingles = (arr) => {
  const out = [];
  let run = '';
  for (const w of arr) {
    if (w.length === 1) run += w;
    else { if (run) { out.push(run); run = ''; } out.push(w); }
  }
  if (run) out.push(run);
  return out;
};

// Kelime (tekrarlar tekilleştirilmiş, ASCII). ^...$ tam eşleşme, sonda \w* ile ek alabilir.
const BAD = [
  /^(amk|amq|aq|mk|mq|amina\w*|amcik\w*|amcuk\w*|amck\w*|aminakoy\w*|amnskm)$/,
  /^(sik|siktir\w*|sikis\w*|sikim\w*|sikik\w*|sikeyim|siker\w*|sikti\w*|sikmek|sikerim|sikecem|sikcem|siksin\w*)$/,
  /^(orospu\w*|orspu\w*|oruspu\w*|orosbu\w*)$/,
  /^(pic|picler|pickurusu|piclik)$/,
  /^(yarak\w*|yarrak\w*|yarag\w*|dalyarak\w*|dalyarrak\w*)$/,
  /^(got|gotun\w*|gotu|gotveren\w*|gotlek\w*|gotos)$/,
  /^(ibne\w*|pust|pusst\w*|gavat\w*|kahpe\w*|kaltak\w*|serefsiz\w*|haysiyetsiz\w*|pezevenk\w*|surtuk\w*|dingil|taksak)$/,
  /^(fuck\w*|fck|shit\w*|bitch\w*|asshole\w*|cunt\w*|nigg\w+|whore|slut|bastard|motherfucker)$/,
];
// Başı eşleşse de masum olanlar (şüphe halinde serbest bırak)
const SAFE = /^(sikayet\w*|sikke\w*|siklon\w*|siklet\w*|sikl[ao]m\w*|gotik|gotur\w*|pusula\w*|pustu\w*|pick\w*)$/;
// Ayraçla bölünmüş yazımı yakalamak için, bitişik halde bile yasak olan güçlü kökler
const STRONG = ['orospu', 'oruspu', 'yarrak', 'amcik', 'siktir', 'aminakoy', 'fuck', 'pezevenk', 'motherfucker'];

let EXTRA = [];
/** Tema ayarındaki ek yasak kelimeler (theme.json "filter.extraWords"). */
export function setExtraWords(list) { EXTRA = Array.isArray(list) ? list.map(String) : []; }

export function hasProfanity(text, extraIn = []) {
  const extra = [...EXTRA, ...extraIn];
  const ws = joinSingles(words(text));
  const extras = extra.map((x) => words(x).join(''));
  for (const w of ws) {
    if (SAFE.test(w)) continue;
    if (BAD.some((re) => re.test(w))) return true;
    if (extras.some((x) => x && (w === x || (x.length >= 4 && w.startsWith(x))))) return true;
  }
  const glued = ws.join('');
  return STRONG.some((s) => glued.includes(s)) || extras.some((x) => x.length >= 5 && glued.includes(x));
}

/** İsim: küfürlüyse yedek ad, değilse aynen. */
export function cleanName(name, fallback = 'Misafir', extra = []) {
  return hasProfanity(name, extra) ? fallback : name;
}

/** Sohbet: küfürlüyse boş metin (bildirim yine sayılır ama ekranda/seste görünmez). */
export function cleanChat(text, extra = []) {
  return hasProfanity(text, extra) ? '' : text;
}
