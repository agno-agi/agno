# Cenaze Alayı: TikTok CANLI overlay'i

TikTok CANLI yayınında izleyicinin gönderdiği hediye ve yorumları, ekrandaki bir cenaze alayında role çeviren etkileşimli 3D overlay. Mizah / kurgu yayını için hazırlanmıştır.

Proje, [duycuf/tiktok-live-kit](https://github.com/duycuf/tiktok-live-kit) (MIT) temel alınarak yapıldı. Her şey [`tiktok-live-kit/`](tiktok-live-kit/) klasöründedir.

## Hızlı başlangıç

```
cd tiktok-live-kit
pnpm install && pnpm start      # Windows'ta run.bat
```

- Kontrol paneli: http://localhost:3939/
- Overlay: http://localhost:3939/overlay
- Testler: `pnpm test`

## Hediye rolleri

| Tetikleyici | Rol |
|---|---|
| Gül, TikTok, Heart Me, GG ya da 1–9 jeton | Omuz ver: gönderen tabutun yanında yürür (en çok 6 kişi) |
| Parmak Kalp | Fotoğrafı taşı: çerçeveyi tabutun önünde taşır (tek kişi) |
| 10–99 jeton | Çelenk |
| 100 jeton ve üstü | Büyük saygı: alay durur (12 sn bekleme) |
| Yorumda "katıl" | Alayın arkasına katılır |

Aynı hediye her zaman aynı sonucu verir, şans yok.

## Nereden başlamalı

| Belge | İçerik |
|---|---|
| [HANDOFF.md](tiktok-live-kit/docs/HANDOFF.md) | Durum, yapılanlar, yapılacaklar, kurallar |
| [GO-LIVE.md](tiktok-live-kit/docs/GO-LIVE.md) | Canlıya çıkış ve yayın öncesi kontroller |
| [themes/cenaze/README.md](tiktok-live-kit/themes/cenaze/README.md) | Cenaze teması ayrıntıları |
| [tiktok-live-kit/README.md](tiktok-live-kit/README.md) | Çatının genel anlatımı |

## Kurallar

- Telifli görsel, müzik ya da dizi sesi kullanılmaz.
- Gerçek bir kişinin fotoğrafı ya da yüzüne benzeyen model kullanılmaz. Levhada yüzsüz siluet vardır.
- Yayın başlığında "mizah / kurgu yayını" ibaresi kalır.

## Bu depo hakkında

Bu depo [Agno](https://github.com/agno-agi/agno) deposunun bir kopyası olarak açıldı. Agno'nun kendi kodu (`libs/`, `cookbook/`, `evals/` vb.) ve lisansı olduğu gibi duruyor. Bu projeyle ilgisi yoktur. Agno'nun orijinal README'si için [özgün depoya](https://github.com/agno-agi/agno) bakın.
