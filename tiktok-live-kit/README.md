# TikTok Live Kit

**Türkçe** · Kaynak: [duycuf/tiktok-live-kit](https://github.com/duycuf/tiktok-live-kit) (MIT) · Bu kopyada Türkçeleştirme, `themes/cenaze` anma teması ve küfür filtresi eklenmiştir.

**TikTok CANLI için etkileşimli oyun / overlay** hazırlamaya yarayan ortak bir çatıdır. İzleyiciler katıldığında, yorum yazdığında, kalp bıraktığında veya hediye gönderdiğinde ekrandaki karakterler ve efektler tepki verir.

Çekirdek bir kez yazılmıştır. Her konu (kafe, dans pisti, anma…) `themes/` içine bırakılan bir **temadır** ve kontrol panelinden canlı olarak değiştirilir.

Bu kopyada hazır tema olarak `themes/cenaze` (anma yayını) ve kendi temanız için kopyalanacak boş `themes/template` (2D) vardır. Temanın görünüşü, hazırladığınız dosyalardan (arka plan, karakterler, GIF, video, müzik) gelir.

| Belge | İçerik |
|---|---|
| [docs/IDEA.md](docs/IDEA.md) | Tema fikriniz: yapmadan önce yanıtlanacak sorular (mekân, izleyiciler, hediyeler, sohbet, ses, görseller) |
| [docs/THEME.md](docs/THEME.md) | Tema yapımı: yapı, `scene.json`, `theme.json`, eylemler, ses, `theme.js` |
| [docs/ASSETS-GUIDE.md](docs/ASSETS-GUIDE.md) | Güzellik nereden gelir: arka plan, karakter sayfası, efektler, yapay zekâ görsel araçlarıyla ses/görsel, işleme araçları |
| [docs/GO-LIVE.md](docs/GO-LIVE.md) | Canlıya çıkış: LIVE Studio / OBS, TikFinity, yayın öncesi kontroller, sık sorunlar |
| [themes/cenaze/README.md](themes/cenaze/README.md) | Anma teması: hediye eşleme, ön saf, küfür filtresi |
| [AGENTS.md](AGENTS.md) | Yapay zekâ kodlama ajanları için: depo haritası, komutlar, kurallar |
| [CHANGELOG.md](CHANGELOG.md) | Değişiklikler |

## Temanızı yapın

1. **Önce fikir.** [docs/IDEA.md](docs/IDEA.md) dosyasını okuyun: mekân ne, izleyiciler kim olur, her hediye ne yapar, sohbet komutları, ses cümleleri, hangi görselleriniz var. Boş bırakıp yapay zekânın sormasına da izin verebilirsiniz.
2. **Yapay zekâyla yapın.** Kit klasörünü Claude Code / Codex / Cursor ile açıp şunu söyleyin: *"AGENTS.md dosyasını oku ve yeni tema için docs/IDEA.md ile benimle röportaj yap."* Ajan bir seferde birkaç soru sorar, yanıtlarınızı tek sayfalık plana çevirir ve siz onaylayınca başlar.
3. **Deneyin.** Kontrol panelinde yeni temayı seçin, **Deneme** sekmesini kullanın, sonra canlıya çıkın ([docs/GO-LIVE.md](docs/GO-LIVE.md)).

### Temayı kendi reposunda tutmak

Her canlı kanal, yalnızca temasını ve verisini tutan ayrı bir repo olabilir; kitin sunucusu üç ortam değişkeniyle çalıştırılır:

| Değişken | Anlamı |
|---|---|
| `KIT_THEMES_DIR` | Temalarınızın klasörü (kitin `themes/` klasöründen önceliklidir) |
| `KIT_DATA_DIR` | Düzenlenmiş kuralların, canlı oturumların, ses dosyalarının tutulduğu yer (varsayılan: kitin `data/` klasörü) |
| `KIT_CONFIG` | Kitin `config.json` dosyasını ezen yapılandırma (ör. `{"theme": "my-theme"}`) |

```bat
set KIT_THEMES_DIR=%~dp0themes
set KIT_DATA_DIR=%~dp0data
set KIT_CONFIG=%~dp0config.json
node ..\tiktok-live-kit\src\server.js
```

## Canlı yayın düzeni

```
TikTok CANLI ──> TikFinity Desktop ──ws://127.0.0.1:21213──┐
          └──> (yedek) doğrudan bağlantı ──────────────────┤
                                                           ▼
                                    Çekirdek (Node, port 3939)
                                    tekrar filtresi · kombo · hediye kuralları · sıralama · unvanlar · hedefler
                                                           │ WebSocket
                         ┌─────────────────────────────────┴───────────────┐
                Kontrol paneli (/)                                 Tema overlay'i (/overlay)
                                                                          │
                       LIVE Studio (overlay.bat penceresinin yakalanması) veya OBS (Tarayıcı kaynağı)
```

## Çalıştırma

Node.js 20 veya üstü gerekir.

- Windows: **`run.bat`** dosyasına çift tıklayın (bağımlılıkları kurar, sunucuyu başlatır, kontrol panelini açar).
- Ya da:
  ```bash
  pnpm install
  pnpm start
  ```

Kontrol paneli için http://localhost:3939/ adresini açın.

## Canlıya çıkış

Kısaca: `run.bat` çalıştırın → TikFinity Desktop'ı açıp kanalınıza bağlayın → kontrol panelinde **Bağlan**'a tıklayın (kaynak **Otomatik**) → `overlay.bat` çalıştırıp LIVE Studio'da **Pencere yakalama** kaynağı ekleyin (veya OBS'de Tarayıcı kaynağı `http://localhost:3939/overlay`, 1080 × 1920). Adım adım anlatım ve sık sorunlar: [docs/GO-LIVE.md](docs/GO-LIVE.md).

Ağ kopması, TikFinity'nin yeniden başlaması veya yayın uygulamasının sayfayı yenilemesi için bir şey yapmanız gerekmez:
- Çekirdek 2'den 30 saniyeye açılan aralıklarla yeniden bağlanır.
- Overlay yeniden bağlanır ve mevcut kalabalığı yeniden kurar.
- Sıralama diske kaydedilir; sunucu yeniden başlasa da korunur.

## Kontrol paneli

Beş sekme; overlay önizlemesi ve ilk 3 gönderen her zaman sağdadır:

- **Canlı**: kaynak seçimi, bağlanma, durum ve "son olay N saniye önce" göstergesi (veri akıyor mu), tema ayarları, olay günlüğü.
- **Kurallar**, web'den düzenlenir, kod gerekmez:
  - Sahneye kimlerin gireceği: herkes, ya da yalnızca anahtar sözcük yazan / hediye gönderen.
  - Tek hediye fiyatına göre hediye kademeleri.
  - Kimliğe veya ada göre hediyeye özel kurallar; canlıda görülen hediyeleri (görsel, ad, fiyat) öğrenen bir **hediye kitaplığı**: birine tıklayıp kural eklenir.
  - Bekleme süreli sohbet komutları.
  - Her satırdaki ▶ düğmesi, kaydetmeden önce o satırın efektini önizler.
- **Deneme**: sahte izleyiciler, kalabalık dalgaları (10 / 30 / 60 / 400 kişi; makinenin dayanıp dayanmadığını görmek için), otomatik mod (normal / yoğun / tıklım tıklım), fiyata göre gruplanmış hediye düğmeleri (küçük / orta / büyük), temanın her efekti için düğme, ses denemesi. Sahte olaylar gerçek canlıyla aynı işlem hattından geçer.
- **İstatistik**: oturum toplamları, unvanlı sıralama, destekçilere teşekkür için **CSV** indirme, hedefler, **Yeni oturum** düğmesi.
- **Rehber**: 4 adımda canlıya çıkış, üç yayın düzeni, faydalı overlay adresleri, sık sorunlar.

Tema çalışırken değiştirilebilir; overlay kendini yeniler.

## Tema yapımı

Bkz. [docs/THEME.md](docs/THEME.md). Özet: `themes/template` klasörünü kopyalayın, görselleri `assets/` içine koyun, sahneyi `scene.json` içinde ölçün, sonra her hediye kademesinin eylemini `theme.json` içinde tanımlayın. Özel efektler için `theme.js` yazın. Tema 2D (arka plan görseli + karakter sayfaları) veya 3D (`"renderer": "3d"`: GLB modeller, gerçek kamera, ışıklar; THEME.md içindeki "3D sahneler" bölümüne bakın) olabilir ya da her şeyle (DOM, Canvas) çizim yapabilir. Unity gibi dış oyunlar da `/ws` WebSocket'ine `{"type":"hello","role":"overlay"}` ile bağlanabilir.

## Yapı

```
src/
  server.js            HTTP + WebSocket, kontrol/overlay rolleri, tema yükleme
  core/
    normalize.js       her kaynaktan ham veri → tek ortak olay biçimi
    profanity.js       küfür filtresi (isimler ve sohbet)
    streaks.js         hediye kombosu (yalnızca artan kısım sayılır, çift sayım yok)
    rules.js           kurallar: hediye ID → hediye adı → fiyat kademesi; sohbet komutları; giriş anahtar sözcükleri
    engine.js          işlem hattı: tekrar filtresi → kombo → kurallar → oturum → yayın
    session.js         oyuncular, sıralama, unvanlar, hedefler, kalıcılık, CSV dışa aktarma
    gift-catalog.js    görülen hediyeleri hatırlar
    voice.js, tts.js   ses cümle şablonları (yorum filtresi, bekleme süreleri), Türkçe TTS, önceden okunan sabit cümleler
    draws.js           sohbet kuraları (dilek kartı, kart çekme...)
  providers/           tikfinity · connector (doğrudan) · demo · manager (yeniden bağlanma, kaynak değiştirme, sessizlik bekçisi)
public/
  control/             kontrol paneli
  sdk/                 live-sdk (bağlantı) · geometry · assets · fx · audio · scene (kalabalık, kamera) · hud · kit (JSON eylemleri çalıştırır)
themes/<id>/           theme.json + scene.json + index.html + theme.js + assets/
data/                  (git'te yok) ayarlar, düzenlenmiş kurallar, canlı oturumlar, hediye listesi
tools/                 görsel işleme: cut-sheet.py (pnpm assets:cut), black-to-alpha.py (pnpm assets:alpha)
test/                  pnpm test
run.bat, overlay.bat   sunucuyu başlatır; overlay'i LIVE Studio'nun yakalayacağı Chrome penceresi olarak açar
```

## Yapılandırma

`config.json` varsayılanları tutar. Kontrol panelinde değişen her şey (kanal, kaynak, tema) ayrıca `data/settings.json` içine kaydedilir.

| Anahtar | Anlamı |
|---|---|
| `port`, `host` | Varsayılan `127.0.0.1:3939`, yalnızca bu bilgisayar. `host` liste kabul eder (`"127.0.0.1,192.168.137.1"`), tam olarak bir adres daha açar (ör. bilgisayarın Wi-Fi erişim noktası) |
| `allowLan` | `true` ise yerel ağdaki diğer makineler bağlanabilir (ör. telefondan kontrol) |
| `provider` | `auto` \| `tikfinity` \| `connector` |
| `tikfinityUrl` | Varsayılan `ws://127.0.0.1:21213/` |
| `autoConnect` | Sunucu başlayınca otomatik bağlanır |
| `signApiKey` | Doğrudan kaynak hız sınırına takılırsa Euler Stream anahtarı |
| `maxJoinsPerSecond` | Yoğun yayınlarda giriş seline üst sınır (varsayılan 15/sn) |
| `playerTtlMinutes` | Sessiz izleyicinin sahneden çıkmadan önce ne kadar kalacağı |
| `watchdogSeconds` | Bu süre olay gelmezse doğrudan kaynağı yeniden bağlar |

## Notlar

- Doğrudan kaynak (`tiktok-live-connector`) resmi olmayan bir kütüphanedir. TikTok protokolü değiştirirse `pnpm update tiktok-live-connector` çalıştırın. Ana kaynak olarak TikFinity tercih edilir.
- Yoğun yayınlarda TikTok her girişi ve her kalbi göndermez. Hediyeler ve yorumlar neredeyse eksiksizdir.
- Ses ve şablon metinleri Türkçedir: TTS iki `tr-TR` sesini kullanır (`src/core/tts.js` içindeki `VOICES`). Ses cümleleri `theme.json` içindedir.
- İsimler ve sohbet `src/core/profanity.js` ile süzülür; ek yasak kelimeler `theme.json` > `filter.extraWords` içine yazılır.

## Lisans

[MIT](LICENSE) (özgün yazar: duycuf, dosya değiştirilmemiştir). Kit bağımsız bir projedir; TikTok ile ilişkisi yoktur, TikTok tarafından onaylanmamıştır. Temaya koyduğunuz görseller, müzikler, yazı tipleri kendi lisanslarına tabidir.
