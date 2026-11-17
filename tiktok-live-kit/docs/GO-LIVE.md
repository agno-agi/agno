# Canlıya çıkış

Bir temayı TikTok CANLI'ya almanın teknik kısmı. Hesap gereksinimleri ve TikTok'un içerik kuralları için TikTok / LIVE Studio'ya bakın.

```
TikTok CANLI ──(hediye, kalp, sohbet)──> TikFinity Desktop ──ws://127.0.0.1:21213──┐
            └──(yedek) doğrudan bağlantı ─────────────────────────────────────────┤
                                                                                   ▼
                                                              Kit (run.bat, port 3939)
                                                                                   │
                        LIVE Studio / OBS <── overlay http://localhost:3939/overlay
```

## 0. Bir düzen seçin

Önce iki soruyu yanıtlayın: **görüntüyü hangi uygulama yayına verecek** ve **hesap neye izin veriyor** (LIVE Studio erişimi mi, TikTok'tan yayın anahtarı mı)?

| Düzen | Gerekenler | Her canlıda | Notlar |
|---|---|---|---|
| **A. LIVE Studio, pencere yakalama** | LIVE Studio erişimi | `run.bat` + `overlay.bat` | En basiti; Studio overlay'in Chrome penceresini yakalar |
| **B. OBS → Sanal Kamera → LIVE Studio** | LIVE Studio erişimi, OBS | `run.bat` + OBS | **En akıcısı**: OBS overlay'i kendisi çizer, kaynak sahnede kayıtlıdır, `overlay.bat` gerekmez |
| **C. Yayın anahtarıyla OBS** | Hesap için yayın anahtarı, OBS | `run.bat` + OBS | Doğrudan OBS'den yayın yapar, Studio gerekmez |

LIVE Studio hesabın erişimi olmadığını söylüyorsa hesap henüz bilgisayardan yayın yapmaya uygun değildir: önce bunu TikTok'ta çözün. Düzen ne olursa olsun `run.bat` canlı boyunca çalışmalıdır: overlay'i, sesi ve canlı veriyi o sunar.

## 1. Gereksinimler

| Yazılım | Notlar |
|---|---|
| Node.js 20+ | https://nodejs.org (eksikse `run.bat` söyler) |
| Chrome | Düzen A: LIVE Studio'nun yakalaması için overlay penceresini açar (Studio Chrome pencerelerini listeler) |
| TikTok LIVE Studio veya OBS | Yayın uygulaması |
| TikFinity **Desktop** (önerilir) | Kurulu uygulama (web sürümü 21213 portunu açmaz). Yoksa doğrudan bağlantıyı kullanın |

## 2. Kiti çalıştırın

1. `run.bat` çalıştırın (ilk seferde bağımlılıkları kurar). Siyah pencere sunucudur: **tüm canlı boyunca açık tutun**.
2. Kontrol paneli http://localhost:3939 adresinde açılır: tema seçin, bağlantı durumuna bakın, efektleri deneyin, demoyu açıp kapatın. **Rehber** sekmesi bu sayfanın özetidir.

## 3. Overlay'i yayın uygulamasına koyun

**A. TikTok LIVE Studio (pencere yakalama)**
1. `overlay.bat` çalıştırın: overlay'i kendi dikey Chrome penceresinde açar; **sesi kendisi çalar** ve **başka pencereler üstünü örttüğünde donmaz**.
2. Studio: dikey düzen → **Kaynak ekle → Pencere yakalama → chrome.exe** (başlık tema adıdır).
3. Kaynağı seçin → çerçeveyi kaplaması için **doldur** (esnetme değil) yapın. Canlı çerçeve 9:16'dan uzundur, bu yüzden her yandan yaklaşık 100px kesilir: yazı ve panelleri güvenli bölgede tutun (`/overlay?safe`).
4. Overlay penceresini küçültmeyin; başka pencerelerin arkasında kalması sorun değildir.
5. Ses: Studio'nun ses ayarlarında masaüstü sesi yakalamayı açın.

**B ve C. OBS** (bir kez kurulur, OBS hatırlar)
1. Ayarlar → Video: temel ve çıkış çözünürlüğü 1080 × 1920, 30 FPS.
2. Kaynaklar → **Tarayıcı**: URL `http://localhost:3939/overlay`, genişlik 1080, yükseklik 1920, *Sesi OBS ile kontrol et* işaretli. Sağ tık → Etkileşim, sesi açmak için overlay'e bir kez tıklayın.
3. **B, LIVE Studio'ya**: OBS → *Sanal Kamerayı Başlat*. Sanal kamera yalnızca görüntü taşır, bu yüzden tarayıcı kaynağının sesini hoparlörden çaldırın: Düzenle → Gelişmiş Ses Özellikleri → Ses İzleme → **İzle ve Çıkış Ver**. Studio'da: dikey düzen → **Kaynak ekle → Kamera → OBS Virtual Camera**, çerçeveyi doldurun, masaüstü sesi yakalamayı açın.
4. **C, yayın anahtarıyla**: Ayarlar → Yayın → Özel, TikTok'tan aldığınız sunucu URL'sini ve yayın anahtarını yapıştırın → *Yayını Başlat*. Ses doğrudan OBS'den gider.

Bir sonraki sefer: `run.bat` çalıştırın, OBS'yi açın (B için sanal kamerayı başlatın). Overlay boşsa kaynağa sağ tık → Yenile.

Karakterleri kendi kameranızın veya videonuzun üstüne koymak için: kontrol panelindeki tema ayarlarında **OBS için yeşil arka plan**'ı açın, sonra Tarayıcı kaynağına **Chroma Key** filtresi ekleyin.

30 FPS ile yayın yapın: overlay kare hızını zaten sınırlar (`scene.json` `"fps": 30`), işlemciyi yayın uygulamasının kodlayıcısına bırakır.

## 4. Canlı veriyi bağlayın (hediye, kalp, sohbet)

**TikFinity Desktop ile**: TikFinity'yi açın, giriş yapın, kullanıcı adı kutusuna kanalın tam @adını girin (@ olmadan), TikFinity'nin canlıya bağlandığını söylemesini bekleyin. Kontrol paneli: **TikFinity Desktop** seçin → **Bağlan**.

**Doğrudan**: kontrol panelinde **Doğrudan**'ı seçin, kanal adını yazın → **Bağlan** (kanal canlıya geçtikten sonra).

**Otomatik**: TikFinity varsa onu kullanır, yoksa doğrudan bağlanır. Kopunca yeniden dener (aralık 30 saniyeye kadar açılır).

Yeşil durum noktası ve ilerleyen "son olay … önce" satırı veri aktığı anlamına gelir.

## 5. Yayına çıkmadan önce

- **Deneme** sekmesinde: efektleri ve hediye düğmelerini deneyin, **Ses denemesi**ni kullanın, makinenin dayanıp dayanmadığını görmek için 60 veya 400 kişilik kalabalık bırakın.
- Otomatik mod kalabalık bir sahne gösterir; gerçek canlıdan önce **kapatın** ve **İstatistik** sekmesinden **Yeni oturum**'a tıklayın (gerçek canlıya bağlanmak demoyu da durdurur).
- Yazı ve panellerin güvenli bölgede olduğunu görmek için `/overlay?safe` açın.
- Sabit cümleler (kuralar, periyodik metinler, davetler) sunucu başladıktan birkaç dakika sonra önceden okunur: kiti canlıdan epey önce başlatın.

## Sık sorunlar

| Belirti | Ne yapmalı |
|---|---|
| Studio'nun pencere yakalaması siyah, "video sinyali kayboldu" | Overlay'i `overlay.bat` ile (Chrome) açın, doğru chrome.exe'yi seçin; Studio'da kaynağı yenileyin |
| Overlay penceresi Studio listesinde yok | Studio Edge uygulama pencerelerini listelemez: Chrome kullanın (`overlay.bat` Chrome'u tercih eder) |
| Overlay sessiz | `overlay.bat` penceresi sesi kendisi çalar; normal tarayıcı sekmesinde bir kez tıklayın. Studio'da masaüstü sesini açın |
| Overlay boş, sahne yok | Genelde sunucu yeniden başlarken açılmıştır; sayfa 12 saniye sonra kendini yeniler, ya da F5'e basın |
| "TikFinity ws://127.0.0.1:21213 adresinde bulunamadı" | TikFinity Desktop açık değil / canlıya bağlı değil ya da web sürümünü kullanıyorsunuz. Ya da Doğrudan'a geçin |
| Doğrudan bağlantı Room ID alamıyor | Kanal henüz canlı değil ya da kanal adı yanlış |
| TikFinity `user_not_found` diyor | Görünen adı değil @adı girin |
| Ses yavaş veya kesik | Microsoft'un TTS servisi kararsızdır: sabit cümleler önceden okunur; tamamen başarısız olunca Windows'un yerleşik Türkçe sesini kullanmak için temaya `"voice": { "fallback": "local" }` yazın |
| Yazı ve paneller telefonlarda kesiliyor | Güvenli bölgede tutun (`?safe`), kenarlardan en az 100px içeride |
| Siyah pencereyi yanlışlıkla kapattım | `run.bat` tekrar çalıştırın, Bağlan'a tekrar tıklayın; görüntü gittiyse Studio'da kaynağı yeniden seçin (OBS: tarayıcı kaynağını yenileyin) |
| B: Studio görüntüyü gösteriyor ama ses yok | Sanal kamerada ses yoktur: OBS tarayıcı kaynağını *İzle ve Çıkış Ver* yapın, Studio'da masaüstü sesini açın |
| B: Studio'nun kamera listesinde "OBS Virtual Camera" yok | Studio'yu açmadan önce OBS'de sanal kamerayı başlatın ya da Studio'yu yeniden başlatın |
