# AGENTS.md

Bu depoda çalışan yapay zekâ kodlama ajanları (Claude Code, Codex, Gemini CLI, Cursor…) için talimatlar. `CLAUDE.md` ve `GEMINI.md` buraya yönlendirir. Kullanıcıya kendi dilinde yanıt verin; belgeler Türkçedir.

## Bu depo nedir

TikTok Live Kit: TikTok CANLI olaylarını (hediye, kalp, sohbet, giriş) alan bir Node sunucusu ve bir **tema** aracılığıyla tepki veren 1080 × 1920 overlay. Kullanıcılar çoğunlukla ajandan **yeni bir tema yapmasını** veya **bir temayı ayarlamasını** ister; çekirdeği değiştirmek nadiren gerekir.

| Yol | İçerik |
|---|---|
| `src/server.js` | HTTP + WebSocket, tema yükleme, ses, otomatik içerik |
| `src/core/` | Olay hattı: normalize → streaks (kombo) → rules → engine → session; `voice.js`, `tts.js`, `draws.js`, `profanity.js` (küfür filtresi) |
| `src/providers/` | Kaynaklar: TikFinity, doğrudan bağlantı, demo, manager (yeniden bağlanma) |
| `public/control/` | Kontrol paneli (`/`) |
| `public/sdk/` | Overlay SDK: `kit.js` (JSON eylemlerini çalıştırır), `scene.js` (2D kalabalık, kamera), `scene3d.js` (aynı API, Three.js, `"renderer": "3d"`), `stage3d.js` (3D hareketli ışıklar, lazerler, video ekranları, `fx3d` efektleri), `fx.js`, `audio.js`, `hud.js`, `assets.js`, `geometry.js`, `live-sdk.js` |
| `themes/template/` | Yeni tema için kopyalanacak boş 2D şablon |
| `themes/cenaze/` | Anma teması (hediye eşleme, ön saf koltukları, küfür filtresi; bkz. kendi README'si) |
| `tools/` | Görsel işleme: karakter sayfası kesici, siyah → şeffaf |
| `docs/` | `IDEA.md` (tema fikri anketi), `THEME.md` (tam başvuru), `ASSETS-GUIDE.md` (görsel hazırlama), `GO-LIVE.md` (canlıya çıkış) |
| `test/` | `node --test` |

## Komutlar

```bash
pnpm install          # ilk seferde (veya Windows'ta run.bat)
pnpm start            # sunucu http://localhost:3939 adresinde
pnpm dev              # src/ değişince yeniden başlar
pnpm test             # çekirdek testleri
pnpm assets:cut  <sheet.png> <out.png> --auto --scale 0.7 --preview <check.png>   # yeşil perde karakter sayfasını keser
pnpm assets:alpha <in.jpg> <out.png> --max 1024                                   # siyah arka planlı efekti şeffaflaştırır
```

`assets:*` komutları [uv](https://docs.astral.sh/uv/) gerektirir (pillow, numpy indirir).

## Tema yapmak

Kit hazır tema ile gelmez; `themes/template` yalnızca boş bir iskelettir. Kullanıcı yeni tema istediğinde (veya sadece "başlamama yardım et" dediğinde):

0. **Önce röportaj, sonra kod.** `docs/IDEA.md` dosyasını bir seferde birkaç soruyla birlikte gözden geçirin: mekân ve hava, izleyiciler kim olur, her hediye kademesi ne yapar, sohbet komutları ve kuralar, unvanlar ve hedefler, ses cümleleri, elindeki görseller, nasıl canlıya çıkacakları. Emin olmadıklarında 2–3 somut seçenek sunun. Sonra `IDEA.md` sonundaki tek sayfalık planı yazın ve dosya oluşturmadan önce **onaylarını bekleyin**. `IDEA.md` doldurulmuşsa okuyun ve yalnızca eksikleri sorun.
1. `themes/template` klasörünü `themes/<tema-adı>` olarak kopyalayın (İngilizce, kebab-case). `config.json` içinde `"theme": "<tema-adı>"` ayarlayın veya kontrol panelinden seçin.
2. **Görseller** (röportajdan): yoksa `docs/ASSETS-GUIDE.md`'ye yönlendirin ve oradaki şablonlardan prompt'lar yazın. Kullanıcı istemedikçe gerçek görsel yerine kodla çizim yapmayın (kodla çizim yalnızca kullanıcı istediğinde, örneğin `themes/cenaze` gibi telif sorunundan kaçınmak için).
3. Arka plan → `scene.json`: `/overlay?scene` açın, kişiler zeminde duruncaya dek `horizonY`, `person`, `floor`, `aisle`, `seats`, `points` ayarlarını düzenleyin.
4. `theme.json`: `actions` (adım listeleri), `rules` (hediye kademeleri, sohbet komutları), `voice`, `characters`, `hud`, `colors`, `sounds`; isteğe bağlı `draws`, `periodic`, `prompts`, `reactions`, `titles`, `goals`, `filter`. Her anahtar `docs/THEME.md` içinde.
5. `theme.js` yalnızca JSON yapamadığında yazılır (`Kit.action` ile özel eylem, `Kit.hud` yerine özel HUD, `Kit.fx.preset` ile yeni parçacık).
6. Kontrol: kontrol panelindeki **Deneme** sekmesinde her efekt düğmesine ve hediye düğmelerine tıklayın, 60 / 400 kişilik kalabalık bırakın, sesi deneyin (*Ses denemesi*); yazının güvenli bölge içinde olduğunu görmek için `/overlay?safe` açın.

Tema kendi reposunda da durabilir: `KIT_THEMES_DIR`, `KIT_DATA_DIR`, `KIT_CONFIG` (bkz. README).

## Canlıya çıkış

Kullanıcı canlıya çıkmak veya yayın kurmak istediğinde **adımları vermeden önce sorun**:

1. Görüntüyü hangi uygulama yayına veriyor: overlay penceresini yakalayan LIVE Studio (A), OBS → Sanal Kamera → LIVE Studio (B, en akıcısı), yoksa yayın anahtarıyla OBS (C)?
2. Hesap neye izin veriyor: LIVE Studio'yu zaten kullanabiliyor mu, yoksa yayın anahtarı var mı? Studio erişim yok diyorsa önce bunu TikTok'ta çözmeleri gerekir.
3. Canlı veri: TikFinity Desktop mı, doğrudan bağlantı mı?

Sonra `docs/GO-LIVE.md` içinden yalnızca o yolu anlatın. Her yolda `run.bat` tüm canlı boyunca çalışmalıdır.

## Kurallar

- **Temalar çekirdeği değiştirmez.** Eksik özellikler `theme.js` içine girer; `src/` veya `public/sdk/` yalnızca kullanıcı kiti tüm temalar için yükseltmek istediğinde değiştirilir ve ardından `pnpm test` çalıştırılır.
- **1080 × 1920 çerçeve, telefonda izlenir**: yazı 20px veya üstü; yazı ve panelleri güvenli bölgede tutun (`Kit.safe`: üstte 240px, her yanda 100px, sol yarı y 1250'den, alt y 1760'tan). Arka planın ana nesnesini örtmeyin.
- **İzleyici verisi güvenilmezdir**: ad ve yorumlar DOM'a `textContent` veya kaçışla girer, asla ham `innerHTML` ile değil. İsim ve sohbet ayrıca `src/core/profanity.js` filtresinden geçer.
- **Hediye şansa bağlı olmaz**: aynı hediye her zaman aynı etkiyi yapar (kademe fiyata göre); hediyeyle tetiklenen rastgele ödül / çekiliş eklemeyin.
- **Yoğun canlılar**: sınırsız döngü, parçacık veya ses yok; hazır sınırları kullanın (`maxTags`, `fps`, `sounds.cooldown`).
- **Sayfa her an yenilenebilir**: saklanması gereken durum yalnızca sayfa değişkenlerinden değil, sunucudan gelir (`Live.on('state')`).
- **Ses yalnızca Türkçedir** (`tr-TR` sesleri); `theme.json` içindeki ses cümleleri Türkçe olmalıdır.
- **Şunları commit etmeyin**: `data/` (canlı oturumlar, düzenlenmiş kurallar, ses önbelleği), `assets/raw/`, anahtarlar veya token'lar (`signApiKey`).
- Görsellerin kaynağını `themes/<id>/CREDITS.md` içinde belirtin; telifli görsel ve müzik kullanmayın.
