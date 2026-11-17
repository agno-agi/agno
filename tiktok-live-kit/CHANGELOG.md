# Değişiklik günlüğü

## Bu kopyada yapılanlar

- Kit, [duycuf/tiktok-live-kit](https://github.com/duycuf/tiktok-live-kit) (MIT) kaynağından alındı; `LICENSE` dosyası korundu.
- **Türkçeleştirme:** TTS sesleri `tr-TR` (`tr-TR-AhmetNeural`, `tr-TR-EmelNeural`), overlay/HUD metinleri, sunucu mesajları, kod yorumları, belgeler, araç açıklamaları, `.bat` dosyaları. Vietnamca `*.vi.md` dosyaları kaldırıldı.
- **Onur koltukları:** `seatTop()` (`scene.js` ve `scene3d.js`) artık sıradaki i. kişiyi her zaman `seats[i]` koltuğuna oturtur; sıra değişince kişiler yer değiştirir.
- **Küfür filtresi:** `src/core/profanity.js`; isimler ve sohbet metni `normalize.js` içinde süzülür, sesli okuma da aynı filtreyi kullanır. Ek kelimeler `theme.json` > `filter.extraWords`.
- **Yeni tema:** `themes/cenaze` (anma). Hediye eşleme sabittir (mum / çiçek / tek büyük an), kura veya şans mekanizması yoktur.
- `scene.json` içinde `"hint": false`: arka plan yokken yayında yardım yazısı ve ızgara çizilmez.
- `themes/template-3d` kaldırıldı (3D motor `public/sdk/scene3d.js` içinde duruyor).

## Özgün projenin geçmişi (özet)

- **1.0.1:** ses, sabit cümleler arka planda önceden okunurken selam ve yorum okumalarını artık düşürmez.
- **1.0.0:** ilk ortak sürüm: canlı kaynaklar (TikFinity, doğrudan, demo), çekirdek (tekrar filtresi, kombo, kurallar, sıralama, unvanlar, hedefler), kontrol paneli, overlay SDK, JSON eylemleri, ses, otomatik içerik (kura, periyodik duyuru, davetler), görsel işleme araçları, belgeler.
- **Yayınlanmamış (özgün):** 3D sahneler ve 3D sahne kiti, OBS için yeşil arka plan, beş sekmeli kontrol paneli, `docs/IDEA.md` röportaj formu.
