# Tema yapımı

Tema bir klasördür: görseller ve sesler `assets/` içinde, sahne düzeni `scene.json` içinde, içerik ve kurallar `theme.json` içinde, özel kısımlar (gerekirse) `theme.js` içinde. Çekirdek canlı bağlantıyı, tekrar filtresini, hediye kombolarını, hediye kurallarını, sıralamayı, unvanları, hedefleri ve sesi halleder. Çoğu tema **kod gerektirmez**: yalnızca JSON.

```
themes/<tema-adı>/
  index.html     SDK'yı yükler (themes/template içinden kopyalanır, düzenleme gerekmez)
  theme.json     eylemler, hediye kuralları, sohbet komutları, unvanlar, hedefler, ses, karakterler, HUD
  scene.json     arka plan, perspektif, zemin, koridor, koltuklar, çapa noktaları, ortam efektleri
  theme.js       (isteğe bağlı) özel eylemler / HUD
  assets/        background.jpg, karakterler, efektler, music/*.mp3, sfx/<ad>.mp3
```

## Hızlı başlangıç

1. `themes/template` klasörünü `themes/<yeni-ad>` olarak kopyalayın (İngilizce, kebab-case). Temayı kendi reposunda tutmak için README'deki "Temayı kendi reposunda tutmak" bölümüne bakın.
2. Arka planı `assets/` içine koyun, ölçüm ızgarasını görmek için overlay'i `?scene` ile açın, sonra kişiler zeminde doğru boyda duruncaya dek `scene.json` ayarlarını düzenleyin.
3. `theme.json` dosyasını düzenleyin: hediye kademesine göre eylemler, sohbet komutları, ses.
4. Kontrol panelini açın, temayı seçin; **Deneme** sekmesinde efekt düğmelerine tıklayın ve kalabalık bırakıp yoğun sahneyi görün.

`_` veya `.` ile başlayan klasörler yok sayılır (taslaklar için kullanın).

Hazır örnek: `themes/cenaze` (anma teması; arka plan ve görsel kullanmaz, hepsi kodla çizilir).

## Overlay'i denetleme

| URL | Amaç |
|---|---|
| `/overlay` | OBS / LIVE Studio sayfası (1080 × 1920) |
| `/overlay?mute` | Sessiz (kontrol panelindeki önizleme) |
| `/overlay?scene` | Ölçüm ızgarasını çizer: ufuk, zemin, koridor, engeller, koltuklar, çapa noktaları |
| `/overlay?safe` | TikTok arayüzünün örttüğü veya uzun telefonlarda kesilen alanları kırmızıyla gölgeler (`Kit.safe`) |

1080 × 1920 çerçevedeki güvenli bölgeler: üstte 240px (kanal adı, izleyici), her yanda 100px (uzun ekranlarda kesilir), y 1250'den aşağı sol yarı (yorum kutusu), y 1760'tan aşağı alt kısım (giriş kutusu, hediye düğmesi). Telefonda yazı yaklaşık 1/3'üne küçülür: okunur yazıyı 20px veya üstü tutun.

## scene.json

```jsonc
{
  "background": "assets/background.jpg",       // görsel / video (mp4, webm) / gif
  "hint": false,                               // false: arka plan yokken yayında ızgara ve yardım yazısı çizilmez
  "horizonY": 700,                             // ufuk: kişiler ufka yaklaştıkça küçülür
  "person": {
    "refY": 1000, "refHeight": 60,             // y = refY'de kişi refHeight px boyundadır
    "exponent": 0.45,                          // perspektif dikliği
    "idleStyle": "stand",                      // karakter görseli yokken yer tutucu şekil: stand | kneel
    "cushion": { "width": 0.5, "depth": 0.32, "color": "#6e170f", "light": "#b8392a" }  // diz çöken / oturan kişinin altındaki minder
  },
  "floor": { "top": 1040, "bottom": 1640, "left": 30, "right": 1050 },   // kalabalığın zemin alanı
  "aisle": { "x": 540, "half": [[1000, 34], [1900, 100]], "lane": 90 },  // orta koridor (derinliğe göre yarım genişlik), yürüme şeridi
  "spacing": { "col": 0.8, "row": 0.4 },       // kişiler arası aralık, kişi boyu cinsinden
  "obstacles": [{ "x0": 0, "x1": 105, "y0": 0, "y1": 1130 }],            // sütun dipleri, masalar... buraya kimse durmaz
  "seats": [[440, 980], [640, 980]],           // en çok gönderenler için onur koltukları (sıradaki i. kişi seats[i]'ye oturur)
  "points": { "stage": [540, 930], "focus": [540, 600], "entry": [540, 2000] },  // eylemler, kamera için çapa noktaları
  "emitters": [{ "preset": "smoke", "at": "stage", "every": 90 }],      // sürekli efektler (at: çapa, [x, y] veya x / y)
  "glows": [[300, 760, 40]],                   // titreyen ışıklar [x, y, yarıçap] (mum, lamba)
  "sunrays": { "from": 1060 },                 // yumuşak çapraz güneş ışınları
  "fill": { "rows": 2 },                       // ilk N sırayı daima isimsiz kişilerle doldurur (izleyici sayısına katılmaz)
  "maxTags": 8,                                // aynı anda en fazla isim etiketi (ilk 3 hariç); etiketler üst üste binmez
  "fps": 30                                    // kare sınırı, işlemciyi yayın uygulamasına bırakır
}
```

Kalabalık kendiliğinden yayılır: oda boşken seyrek, kalabalıkken sık; yer kalmayınca en uzun süredir sessiz olan kişi ayrılır.

## theme.json

### Eylemler: JSON adım listeleri

```jsonc
"actions": [
  {
    "id": "small", "label": "Küçük hediye", "icon": "assets/icon.png", "card": "1 jeton",
    "steps": [
      { "walk": "stage" },                                   // çapa noktasına yürür / "home" kendi yerine döner
      { "pose": "stand" },
      { "play": "bow", "times": 3, "each": [{ "sound": "bell" }] },   // animasyonu n kez oynatır ("count" = hediye adedi)
      { "fx": "emit", "preset": "spark", "at": "head", "count": 12 },
      { "fx": "halo", "at": "focus", "image": "assets/fx/halo.png" },
      { "fx": "text", "at": "head", "text": "+{total}" },
      { "camera": "person", "zoom": 1.6 }, { "spotlight": true }, { "aura": 1 }, { "boost": 1.3 },
      { "say": "Teşekkürler {ten}!" }, { "toast": "{ten} az önce {qua} gönderdi" },
      { "crowd": [{ "play": "bow" }] },                      // tüm kalabalık yapar
      { "js": "myAction" }                                   // theme.js içindeki Kit.action('myAction', fn) çağrılır
    ]
  }
]
```

Efektler (`fx`): `emit` (smoke heart spark petal confetti snow leaf bubble firefly ember coin star), `rain`, `halo`, `rays`, `pillar`, `text`, `fly`, `sprite`, `fireworks`, `flash`, `shake`. Kendi görselinizi `"image"` ile verin. Tema `theme.js` içinde `Kit.fx.preset(ad, {...})` ile yeni parçacık türleri tanımlayabilir (bkz. `themes/cenaze/theme.js`).
Adım metinleri `{ten}` (ad) `{qua}` (hediye) `{count}` `{total}` `{label}` kabul eder.

### Kurallar

```jsonc
"rules": {
  "joinMode": "all",                         // "all": etkileşime giren herkes girer; "keyword": anahtar sözcük yazmalı
  "joinKeywords": ["merhaba"],
  "bigGiftCoins": 100,                       // bu jetondan itibaren "bigGift" de çalışır
  "giftTiers": [{ "minCoins": 1, "action": "small", "label": "Küçük hediye" }],   // TEK hediyenin fiyatına göre
  "giftOverrides": [{ "giftId": "5655", "names": ["rose"], "action": "small" }],
  "chatCommands": [{ "keywords": ["dilek"], "match": "contains", "action": "draw", "draw": "fortune", "label": "kart çek", "cooldownMs": 30000 }]
},
"bigGift":   { "steps": [...] },              // büyük hediyeler için ek adımlar
"reactions": { "like": [...], "chat": [...], "follow": [...], "share": [...], "title": [...], "goal": [...] },
"titles": [{ "minCoins": 200, "label": "Koruyucu", "aura": 0.45 }],  // aura: unvana göre kalıcı parıltı (theme.js içinde kullanılır)
"goals":  [{ "id": "likes", "metric": "likes", "label": "Kalp", "every": 1000 }],
"filter": { "extraWords": ["ek", "yasak", "kelimeler"] }   // küfür filtresine ek kelimeler (isim + sohbet)
```

Hediye eşleştirme sırası: **hediye ID** → **ad / takma ad** (aksan fark etmez) → **fiyat kademesi**. Kurallar kontrol panelinden düzenlenebilir ve `data/rules-<id>.json` içine kaydedilir.

İsimler ve sohbet metni `src/core/profanity.js` ile süzülür: küfürlü isim "Misafir" olur, küfürlü yorum hiç iletilmez (ne ekranda ne seste görünür).

### Sohbet kuraları (dilek kartı, kart çekme, fal...)

```jsonc
"draws": { "fortune": { "perDay": true, "items": [{ "title": "Kart 1 · Çok şanslı", "text": "Bugün her şey yolunda gidecek." }] } }
```

`"draw": "fortune"` içeren bir sohbet komutu sunucunun bir öğe çekmesini sağlar (`perDay` ile kişi başına günde tek sabit öğe). Overlay bunu `ev.draw` olarak alır (hazır HUD `title` ve `text` alanlarını gösterir) ve ses `voice.draw` şablonunu kullanır; her öğe alanı bir değişkendir (`{title}`, `{text}`…).

> Not: Kuralar şansa dayanır. Hediyeye bağlı ödül/çekiliş için kullanmayın; hediye eşleme her zaman sabit olmalıdır.

### Ses

```jsonc
"voice": {
  "enabled": true, "voice": "tr-TR-AhmetNeural",              // veya tr-TR-EmelNeural
  "gift": ["{ten}, {qua}{lan} için teşekkürler. {loi}."], "bigGift": [...],
  "join": ["Hoş geldin {ten}!"], "chat": ["{ten} yazdı: {chat}."],   // yorumlar küfür, link, emoji için süzülür
  "follow": [...], "title": [...], "goal": [...],
  "command:wish": ["{ten} dilek gönderdi: {loi}."],          // her sohbet komutu için ayrı cümle (eylem kimliğine göre)
  "draw": ["{ten} şunu çekti: {title}. {text}"], "drawAgain": [...],
  "cooldown": { "join": 18000, "chat": 10000 },               // cümle türüne göre aralık (ms)
  "delay": { "draw": 2300 },                                  // sesin görüntünün çıktığı ana denk gelmesi için bekleme
  "fallbackWords": ["Allah rahmet eylesin"],                 // kişi henüz yazmadıysa {loi} yerine
  "fallback": "local"                                         // (isteğe bağlı) servis çökerse Windows'un yerleşik Türkçe sesi kullanılır
}
```

Değişkenler: `{ten}` ad, `{qua}` hediye, `{lan}` ", N adet", `{xu}` jeton, `{hanh_dong}` eylem etiketi, `{danh_hieu}` unvan, `{muc_tieu}` hedef, `{gia_tri}` hedef değeri, `{loi}` kişinin son sözü, `{chat}` yorum.

Ses, Microsoft'un ücretsiz TTS servisini kullanır (internet gerekir, bazen yavaş); yalnızca iki Türkçe ses desteklenir (`tr-TR-EmelNeural`, `tr-TR-AhmetNeural`). Hediye, kura ve unvan cümleleri öne geçer; selam ve yorum okuma yalnızca kuyruk boşken çalar. Sabit cümleler (kuralar, periyodik metinler, davetler) **önceden okunur ve `data/tts-cache` içinde saklanır**: sonraki sefer anında çalar.

### Otomatik içerik

```jsonc
"periodic": { "everyMinutes": 3, "quietSeconds": 0, "title": "DUYURU", "items": ["..."] },  // quietSeconds > 0: yalnızca sessizken
"prompts":  { "everySeconds": 90, "quietSeconds": 25, "items": ["Kartını çekmek için kura yaz."] }  // sohbet sessizken etkileşim davetleri
```

### Karakterler

```jsonc
"characters": [{
  "id": "guest", "label": "Misafir", "keywords": ["misafir"],      // görünümü değiştirmek için anahtar sözcük yazılır
  "sheet": "assets/chars/guest.png", "frames": 32,                 // eşit karelerden oluşan yatay şerit, şeffaflığa göre otomatik kırpılır
  "walkUp": [0, 1, 2], "walkDown": [8, 9], "walkSide": [12, 13],   // yöne göre yürüme kareleri (yan yürüme sağa bakacak çizilir)
  "poses": { "idle": 16, "stand": 24, "cheer": 26 }
}],
"animations": { "bow": { "frames": ["idle", "idle@0.8", "idle"], "ms": 1300 } },   // "idle@0.8": aşağı doğru basık (eğilme)
"npcs": [{ "id": "host", "character": "guest", "at": [480, 870], "showName": false, "cushion": false, "reactions": { "bigGift": [...] } }]
```

Yapay zekâ ile çizilen karakter sayfaları nadiren eşit aralıklıdır: sayfa kesiciyi kullanın (her pozu bulur, yeşil arka planı siler) `pnpm assets:cut ... --auto`; tam akış [ASSETS-GUIDE.md](ASSETS-GUIDE.md) içinde.

### Hazır HUD, renkler, sesler

```jsonc
"hud": { "title": { "text": "Kanal adı" }, "counters": true, "giftCard": { "verb": "gönderdi:", "unit": "jeton" }, "tiers": true,
         "board": { "title": "ÖN SAF", "size": 3 }, "ticker": { "title": "Son gönderilenler" }, "goal": true, "guide": { "title": "Nasıl katılırım" } },
"colors": { "accent": "#ffd987", "panel": "...", "border": "...", "glow": "..." },
"sounds": { "bell": { "cooldown": 3000, "duck": 0.7 }, "like": false }   // assets/sfx/<ad>.mp3, müzik: assets/music/*.mp3
```

## 3D sahneler (Three.js)

Tema, arka plan görseli yerine 3D sahne kullanabilir: mekân ve karakterler için GLB / glTF modeller, gönderene uçan gerçek kamera, ışıklar ve parlama. Geri kalan her şey aynı kalır: `theme.json` eylemleri, kurallar, ses, HUD, efektler (üstteki 2D katmanda çizilir), isim etiketleri ve sohbet balonları.

3D tema için `index.html` içine Three.js import map'i ve `/sdk/scene3d.js` eklenmelidir (özgün projedeki `themes/template-3d/index.html` örnek alınabilir; bu kopyada o şablon kaldırılmıştır). Model yokken bile eğilen, zıplayan ve yürüyen yer tutucu kişiler (gövde + baş) görünür, böylece akışı önce deneyebilirsiniz.

```jsonc
// scene.json, birim metre: x yana, y yukarı, z kameraya doğru (sahne negatif z'de)
{
  "renderer": "3d",
  "camera": { "position": [0, 7.5, 19], "target": [0, 1.2, 0], "fov": 55 },
  "world": "assets/3d/stage.glb", "worldScale": 1,      // mekân (isteğe bağlı; yoksa düz zemin çizilir)
  "background": "#17141f", "fog": { "color": "#17141f", "near": 22, "far": 48 },
  "lights": { "ambient": 0.9, "sun": { "intensity": 1.6, "position": [6, 12, 8], "shadows": false },
              "points": [{ "at": [0, 3, -4], "color": "#ff8a5c", "intensity": 25, "distance": 12 }] },
  "floor": { "x": [-4, 4], "z": [-0.5, 8] },            // kalabalığın durduğu yer
  "aisle": { "x": 0, "half": 0.6 }, "spacing": 0.8, "fill": { "rows": 0 },
  "seats": [[-1.4, -1.8], [1.4, -1.8]],                 // en çok gönderenler için onur koltukları
  "points": { "stage": [0, -3.2], "focus": [0, 2, -4], "entry": [0, 14] },   // zeminde [x, z] veya [x, y, z]
  "bloom": { "strength": 0.5, "radius": 0.4, "threshold": 0.85 },
  "facing": "focus",                                    // boştaki kişiler "focus" / "stage" noktasına bakar; "camera" = izleyiciye döner
  "maxAnimated": 120, "fps": 30
}
```

```jsonc
// theme.json: 3D karakter, içinde animasyon klipleri olan iskeletli bir GLB'dir
"characters": [{
  "id": "guest", "label": "Misafir", "keywords": ["misafir"],
  "model": "assets/3d/guest.glb", "height": 1.7,        // bu boya (metre) ölçeklenir
  "clips": { "idle": "Idle", "walk": "Walk", "cheer": "Wave", "nod": "Interact", "dance": "Dance" }
}],
"animations": { "bow": { "clip": "Bow", "ms": 1600 } }  // isteğe bağlı: bir "play"in ne kadar sürdüğü
```

`pose` ve `play` adımları `clips` içindeki adları kullanır; eksik ad önce aynı adlı kliple (büyük/küçük harf fark etmez), sonra `idle` ile karşılanır. `walk` hareket ederken kullanılır. Aynı adım listeleri 2D ve 3D'de çalışır: `walk`, `play`, `camera`, `spotlight`, `aura`, `boost`, `say`, `crowd`, `fx`.

Modeller: Quaternius, Kenney, KayKit gibi CC0 paketleri veya Mixamo animasyonları. 1–2 malzemeli, yaklaşık 5 bin üçgenin altındaki karakterleri tercih edin; Radeon 780M dizüstü GPU'da test edildi: yaklaşık 110 Quaternius karakteri (her biri yaklaşık 10 parça, ~1.150 çizim çağrısı) 20–23 ms'de çizilir, 30 fps için yeterlidir. Uzaktaki kişilerin animasyonu daha seyrek güncellenir (`maxAnimated`). `?scene` zemini, duruş yerlerini, koltukları ve noktaları 3D dünyadan yansıtarak çizer.

`theme.js` içinde `Kit.scene.three`, kendi 3D nesnelerinizi eklemeniz için `{ THREE, scene, camera, renderer }` verir.

### Sahne kiti: hareketli ışıklar, lazerler, video ekranı

```jsonc
// scene.json
"stage": {
  "lights": [{ "at": [-4, 6.5, -3], "color": "#ff3cac", "target": [-1.5, 2], "sweep": 2.5, "speed": 0.55, "angle": 14, "intensity": 40, "beam": 0.28 }],
  "lasers": { "from": [0, 5.5, -4.5], "count": 8, "colors": ["#00ffd5", "#ff2bd6"], "spread": 70, "speed": 0.5, "width": 0.035, "always": false },
  "screens": [{ "at": [0, 4.2, -5.5], "size": [5.6, 3.15], "folder": "video" }]   // veya "video": "assets/x.mp4", "videos": [...], "image": "..."
}
```

- **Hareketli ışıklar**: zeminde gerçek bir spot ışığı ve görünen bir huzme, `target` çevresinde tarar. `Kit.fx.beat.bpm` ayarlıysa müzikle atar.
- **Lazerler**: ince ışınlardan yelpaze, `party` sırasında (veya `"always": true` ile hep) görünür.
- **Ekranlar**: döngüde sessiz video; `"folder": "video"`, `assets/video/` içine bırakılan her `.mp4` / `.webm` dosyasını sırayla oynatır (DJ ekranı gibi).

Eylem adımları (2D temalar `stage` adımını yok sayar ve `fx3d` adımını en yakın 2D efekte çevirir, böylece tek theme.json ikisinde de çalışır):

| Adım | Etki |
|---|---|
| `{ "stage": "party", "duration": 7000 }` | ışıklar daha parlak ve hızlı, lazerler açık |
| `{ "stage": "calm" }` / `{ "stage": "strobe", "duration": 1200 }` | normale döner / ışıklar çakar |
| `{ "fx3d": "fireworks", "at": "stage", "bursts": 5 }` | bir noktanın üstünde 3D havai fişek |
| `{ "fx3d": "confetti", "count": 300 }` | tüm kalabalığın üstüne yağan konfeti |
| `{ "fx3d": "beam", "at": "person", "color": "#ffd27a" }` | gönderenin üstünde ışık sütunu |
| `{ "fx3d": "ring", "at": "person" }` | zeminde yayılan parlak halka |

### OBS için yeşil arka plan

Kontrol panelindeki tema ayarlarında **OBS için yeşil arka plan**'ı açın ya da overlay'i `?chroma` ile açın. Arka plan saf `#00ff00` olur (değiştirmek için `scene.json` `"chroma"`); 3D'de zemin, dünya modeli, sis, parlama, huzmeler, lazerler ve ekranlar gizlenir, yalnızca kişiler, etiketler ve efektler kalır. OBS'de Tarayıcı kaynağına **Chroma Key** filtresi ekleyin. 2D temalarda da çalışır.

## theme.js: özel kısımlar

```js
Kit.action('lantern', (person, ev) => { /* { "js": "lantern" } adımı */ });
Kit.on('frame', (t, dt) => { /* her karede */ });
Kit.on('speak', (e) => {}); Kit.on('speakEnd', (e) => {});   // ses cümlesi başlar / biter (e.about: gift, draw, chat...)
Kit.fx.preset('mum', { life: [1600, 2600], size: [4, 8], vy: [-70, -30], shape: 'dot', color: '255,196,110', glow: true });  // yeni parçacık türü
Kit.hud = { init, giftCard, ticker, state, guide, toast, periodic, draw, remember, reset };  // tüm HUD'u değiştirir
```

API: `Kit.scene` (kişiler, çapa noktaları, kamera), `Kit.fx` (efektler), `Kit.audio` (`sfx('bell')`), `Kit.safe` (güvenli bölgeler), `Live.on(...)` (ham olaylar: join, chat, like, gift, command, follow, share, title, goal, periodic, prompt, tts, state, reset).

## Temayı canlıda kararlı tutmak

- **Sınırlı kalın**: yoğun bir canlı saniyede onlarca olay gönderebilir; kit kişileri, etiketleri ve sesleri zaten aynı anda sınırlar, sınırsız döngü eklemeyin.
- **İzleyici verisine güvenmeyin**: HTML'e konan ad ve yorumlar `textContent` veya bir kaçış fonksiyonundan geçmelidir.
- **Sayfa her an yenilenebilir** (OBS, ağ kopması): kit mevcut kişileri yeniden kurar; boş ekranda 12 saniye takılırsa kendini yeniler.
- **Yayında gerçek bir insan olsun**: yalnızca kendi kendine çalışan bir oyun içeren canlı, TikTok tarafından kolayca "özgün olmayan içerik" diye işaretlenebilir. Yayıncı kamerası ve konuşma yardımcı olur.
