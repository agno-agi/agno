# Devir notu (handoff)

Yeni bir oturumun/kişinin kaldığı yerden devam etmesi için. Son güncelleme: 2026-11-18. Dal: `ccr-e9f6b567-qsre58`; `main` ile aynı noktadaydı (son birleştirme `920ad88`).

## Proje
TikTok CANLI için etkileşimli 3D overlay. Temel: [duycuf/tiktok-live-kit](https://github.com/duycuf/tiktok-live-kit) (MIT, `LICENSE` korundu). Bu repo (`mustafabasar7/agno`) aslında Agno'nun bir kopyası; kit `tiktok-live-kit/` klasöründe. Tema: `themes/cenaze` ("Süleyman Çakır cenaze alayı", mizah/kurgu yayını).
Kullanıcı Türkçe konuşur ve hızlı canlıya çıkmak ister; "önce basit, sonra kalite" kararı verildi.

## Çalıştırma
```
cd tiktok-live-kit
pnpm install && pnpm start        # veya Windows'ta run.bat
# Kontrol paneli: http://localhost:3939/   Overlay: http://localhost:3939/overlay
pnpm test                          # 25 test, hepsi geçiyor
```
Yayın yolu önerisi: A (LIVE Studio + `overlay.bat` pencere yakalama); OBS kamerayı kapabildiği için tercih edilmedi. Ayrıntı: `docs/GO-LIVE.md`.

## Yapılanlar
- Kit kopyalandı, her şey Türkçeleştirildi (arayüz, belgeler, yorumlar, TTS `tr-TR`). Vietnamca `*.vi.md` silindi. Testlerdeki Vietnamca örnek veri bilerek kaldı.
- `seatTop()` (`public/sdk/scene.js` ve `scene3d.js`): sıradaki i. kişi her zaman `seats[i]`'ye oturur.
- Küfür filtresi `src/core/profanity.js` (+ `test/profanity.test.js`): isim → "Misafir", küfürlü yorum hiç iletilmez; ek kelimeler `theme.json > filter.extraWords`.
- `themes/cenaze` 3D (`scene.json "renderer": "3d"`), model dosyası yok: yer tutucu insan figürleri (`humanoid`, `humanoidStyle: "suit"`, `procession`), mekân `theme.js` içinde kodla çizilir (gündüz sokak, kayan ağaç/bina, omuzlarda tabut, isim levhası). Bacaklar sallanır, taşıyıcılar ve tabut aynı adımda sekir. `walkSpeed: 3.4`.
- Hediye rolleri (sabit, şans yok): **Omuz ver** (1–9 jeton / Gül, TikTok, Heart Me, GG: gönderen tabut yanında 30 sn durur, 6 kişiye kadar), **Fotoğrafı taşı** (Parmak Kalp: çerçeveyi tabutun önünde taşır, tek kişi), **Çelenk** (10–99), **Büyük saygı** (100+, tek sakin an, 12 sn bekleme). Eşleme: `theme.json > rules.giftOverrides` (ad + bilinen ID'ler). Yoruma "katıl" yazan alaya girer (`joinMode: keyword`).
- Levhada ve taşınan çerçevede **yüzsüz siluet**. İsteğe bağlı `themes/cenaze/assets/portrait.png|jpg` yuvası var (varsa görünür, `.gitignore`'da).
- HUD: alt kademe kutuları kapatıldı (TikTok arayüzüne denk geliyor).

## Kullanılan komutlar / yöntem notları
- Görsel doğrulama: Playwright (hazır) + `--use-gl=swiftshader`; ekran görüntüsünü `/overlay?mute` üzerinden alın. Hediye tetiklemek için sayfa içinde `Live.emit('gift', {...})` veya kontrol WebSocket'ine `{type:'test', action:'an', coins:100}`.
- Başlık/levha adı tek yerden: `theme.json > hud.title.text`.

## Henüz yapılmayanlar / riskler
1. **Gerçek ortamda deneme yok:** ses (TTS bu VM'den denenemedi, internet gerekir; `voice.fallback: local` var), TikFinity/doğrudan bağlantı, performans (60/400 kişi), `/overlay?safe` güvenli bölge, mobil görünüm.
2. **Gerçek hediye adları/ID'leri** canlıda doğrulanmalı (kontrol paneli: Kurallar → Canlıda görülen hediyeler).
3. **Ses/müzik yok** (telifsiz kaynak gerekir; bu VM'den kenney/freesound vb. erişilemedi).
4. **Kalite (ikinci aşama):** CC0 karakter modelleri, Blender ile mekân/tabut, gerçek yürüme animasyonu, gündüz/gece seçeneği.
5. **Hukuki/riskler (kullanıcı sorumluluğunda):** karakter adı bir diziden (Kurtlar Vadisi); kullanıcı Pana Film'den yazılı "sorun yok" mektubu aldığını bildirdi (imzasız/tarihsiz, kapsamı net değil: oyuncunun yüz/görüntü hakkı, fotoğraf telifi, hediye geliri belirtilmiyor). TikTok'un LIVE/hediye kuralları ayrıca kontrol edilmeli. Başlıkta "mizah / kurgu yayını" ibaresi kalmalı.

## Değişmez kurallar (kullanıcıyla netleşenler)
- **Telifli görsel / müzik / ses yok; hediye şans oyunu olmasın** (aynı hediye = hep aynı etki).
- **Gerçek bir kişinin fotoğrafı veya yüzüne benzeyen model üretilmez/yerleştirilmez** (dizi karakterinin oyuncusu dahil); tanımlama yapılmaz. Kullanıcı kendi yetkisiyle `portrait.*` dosyasını elle koyabilir; asistan koymaz. Trellis/Blender ile bir oyuncuya benzer model yapılmaz; özgün karakter için tarif yazılır.
- Dizi ses/replik/sahne görüntüsü kullanılmaz.
- `main`'e yalnızca kullanıcı "maine al" dediğinde alınır (git ile fast-forward / önce `origin/main`'i dala merge).

## Araç/VM notları
- VM: Node, pnpm, Python 3.13 (Pillow, numpy), uv, ffmpeg, Playwright var; **Blender yok, GPU yok**. Model/ses siteleri (kenney, poly.pizza, quaternius, freesound) erişilemiyor; npm ve PyPI erişilebilir. PyPI'de `bpy` (Blender'ı Python modülü olarak) var, uyumlu Python sürümü ve boyut nedeniyle denenmedi.
- `@gltf-transform/cli` (npm) ile GLB sadeleştirme/optimizasyon yapılabilir (Blender gerekmeden).
- Önizleme: sunucu başlatıldıktan sonra `report_preview_port(3939)` ile uygulamaya bildirilir.

## Sıradaki mantıklı adımlar
1. Kullanıcının makinesinde canlı deneme (ses, bağlantı, performans, güvenli bölge) ve düzeltmeler.
2. Gerçek hediye adlarıyla `giftOverrides` düzeltmesi.
3. Telifsiz ses/müzik eklenmesi (kullanıcı indirir, `assets/sfx|music` altına koyar).
4. İkinci aşama kalite: CC0 modeller (kullanıcı indirir), özgün "reis" siluet karakteri.
