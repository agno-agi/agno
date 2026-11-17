# Anma teması (cenaze)

Sakin bir anma yayını için overlay. Hazır görsel/müzik yok; her şey kodla çizilir (bkz. `CREDITS.md`).

## Hediye eşleme (sabit, şansa bağlı değil)
Aynı hediye her zaman aynı etkiyi yapar; rastgele ödül, çekiliş veya "şans" mekanizması yoktur (`draws` bilerek yok).

| Tek hediyenin değeri | Etki |
|---|---|
| 1–9 jeton | **Mum**: gönderenin yanında mum ışığı, hafif baş eğme (kombo sayısı kadar parçacık) |
| 10–99 jeton | **Çiçek**: ön tarafa yürür, baş eğer, karanfil yaprağı bırakır, yerine döner |
| 100+ jeton | **Tek an**: kamera gönderene yaklaşır, ışık sütunu, yavaş yağan yapraklar, tüm saf baş eğer, "Allah rahmet eylesin" + seslendirme (12 sn bekleme) |

## Ön saf (koltuklar)
En çok gönderen ilk 6 kişi, sırayla `scene.json > seats[0], seats[1], …` koltuklarına oturur; sıra değişirse yer değiştirir.

## Filtre
İsimler ve sohbet `src/core/profanity.js` ile süzülür (Türkçe + yaygın İngilizce; harf değiştirme, ayraç, tekrar yakalanır).
Küfürlü isim → "Misafir"; küfürlü yorum → ekrana/sese hiç gitmez. Ek kelimeler: `theme.json > filter.extraWords`.
Sohbet sesli okunmaz (`voice.chat` boş); isterseniz bir şablon ekleyin.

## Kişiselleştirme
Başlık/alt başlık: `theme.json > hud.title`. Tarih, ayet/dua metni vb. aileyle birlikte karar verip oraya eklenmeli.
