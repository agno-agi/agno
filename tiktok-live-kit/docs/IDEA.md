# Tema fikriniz

Kit hazır tema ile gelmez. Bir tema yapmadan önce aşağıdaki soruları yanıtlayın: kendiniz doldurun ya da yapay zekâ kodlama ajanınızın tek tek sormasına izin verin (ajan [AGENTS.md](../AGENTS.md) dosyasını okur). Kısa yanıtlar yeterlidir; "emin değilim" de bir yanıttır, ajan seçenekler önerir.

## 1. Mekân

- **Konu**: canlı yayın nerede geçiyor? (kafe, balık göleti, sınıf, tribün, bahçe, uzay istasyonu, anma salonu…)
- **Hava**: sıcak, komik, enerjik, sakin, ciddi?
- Çerçevenin üstündeki **ana nesne**: sahne, tezgâh, büyük bir ağaç, ekran…
- **Yayıncı**: kamerada siz mi olacaksınız, yoksa sahne tüm görüntü mü?

## 2. İzleyiciler

- Biri katılınca sahnede **kim olur**? (müşteri, hayran, balık, öğrenci, cemaatten biri…)
- Kimler girer: etkileşime giren **herkes** mi, yoksa yalnızca bir **anahtar sözcük** yazan / hediye gönderen mi?
- Beklerken ne yaparlar? (oturur, dans eder, dolaşır, tezahürat yapar, sessiz durur)

## 3. Hediyeler

Her kademe için ekranda ne olur. Bir hediye birden fazla şeyi tetikleyebilir (bir yere yürümek, bir hareket oynatmak, efekt, ses, ses cümlesi).

| Kademe | Hediye başına jeton | Ne olur |
|---|---|---|
| Küçük | 1–9 | ör. kişi parlar ve el sallar |
| Orta | 10–99 | ör. sahneye yürür ve bir hareket yapar |
| Büyük | 100+ | ör. havai fişek, kamera yakınlaşması, tüm kalabalık tezahürat yapar |

Kendi eylemi olan belirli bir hediye var mı? (ör. Gül = çiçek atar)

> Not: Hediye eşleme sabit olmalıdır: aynı hediye her zaman aynı etkiyi yapar. Şansa bağlı ödül veya çekiliş yapmayın.

## 4. Sohbet

- **Komutlar**: izleyiciler ne yazabilir, ne olur? (ör. "dans" → dans eder, "kahve" → fincan belirir)
- **Kuralar**: sohbetle günlük ücretsiz bir kart, fal, dilek veya söz?
- Yorumlar **sesli okunsun** mu?

## 5. İlerleme

- Toplam jetona göre **unvanlar** (ör. Müdavim → VIP → Efsane)?
- Tüm oda için **hedefler** (ör. her 1.000 kalpte bir şey olur)?
- **Sıralama**: en çok gönderenler için onur koltukları veya podyum?

## 6. Ses ve otomatik içerik

Ses Türkçedir (iki ses: kadın Emel, erkek Ahmet).

- Biri **katılınca**, **hediye** gönderince, bir **unvana** ulaşınca ne söylenir?
- **Periyodik duyurular** (birkaç dakikada bir) ve sohbet sessizken **davetler** ("Partiye katılmak için dans yaz!")?

## 7. Görseller

- Elinizde ne var: arka plan, karakterler, efektler, müzik, ses efektleri?
- Eksikler: yapay zekâyla üretin ([ASSETS-GUIDE.md](ASSETS-GUIDE.md)'a bakın) ya da yer tutucu şekillerle başlayın?
- Sanat stili: fotoğraf, 3D, anime, düz çizgi film?
- **2D mi 3D mi?** 2D = tek arka plan görseli + karakter sayfaları (yapay zekâ görselleriyle güzel yapmak kolay). 3D = GLB modeller ve hareketli kamera (ücretsiz CC0 model paketleri var; bilgisayarı daha çok yorar).

## 8. Canlıya çıkış

- Hangi düzen: LIVE Studio pencere yakalama, OBS → sanal kamera → LIVE Studio, ya da yayın anahtarıyla OBS? ([GO-LIVE.md](GO-LIVE.md)'a bakın)
- Canlı veri TikFinity Desktop üzerinden mi, doğrudan bağlantıyla mı?

## Ajanın geri verdiği

Tek satır kod yazmadan önce ajan yanıtlarınızı tek sayfalık plana çevirir ve onayınızı bekler:

```
Tema: <ad> (klasör themes/<kebab-ad>)
Sahne: <arka plan, ana nesne, kalabalığın durduğu yer>
İzleyiciler: <kim olurlar, giriş kuralı, boştaki davranış>
Hediyeler: küçük → <adımlar> · orta → <adımlar> · büyük → <adımlar> · <özel hediyeler>
Sohbet: <komutlar> · <kuralar>
Unvanlar / hedefler: <liste>
Ses: <giriş / hediye / unvan cümleleri> · periyodik: <maddeler> · davetler: <maddeler>
Görseller: var <…> · gerek <…> (ASSETS-GUIDE tarzında hazır prompt'lar)
Canlı: <düzen A / B / C>, <TikFinity / doğrudan>
```
