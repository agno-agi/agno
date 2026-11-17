# Güzellik nereden gelir

Kit hareketi, efektleri, sesi ve oyun kurallarını halleder. **Güzellik görsellerden gelir**: arka plan, karakterler, efektler, ses. Kit hazır görsel ile gelmez; bu rehber kendi görsellerinizi, çoğunlukla yapay zekâ görsel araçlarıyla (GPT Image, Gemini / Flow, Midjourney…) nasıl hazırlayacağınızı gösterir.

```
Katman 4  Arayüz: paneller, kartlar, yazı          ← theme.js içinde CSS ya da hazır hud
Katman 3  Efektler: hale, duman, ışınlar, parçacık ← siyah arka plan → şeffaf
Katman 2  Karakterler, eşyalar                      ← yeşil perde animasyon sayfası → karelere kesilir
Katman 1  Arka plan                                 ← en önemlisi, havanın %70'ini belirler
```

## Genel kurallar

- **Tüm set için tek hava**: önce arka planı üretin, sonra sonraki her görselde o arka planı referans verin (*"bu görselin renklerine ve ışığına uy"*). Her prompt'un sonunda aynı stil bloğunu (STYLE) kullanın.
- **Aynı çizim stili**: fotoğraf arka plan → fotoğraf / 3D karakterler; boyama arka plan → aynı şekilde boyanmış karakterler. Uyumsuzluk hemen "yapıştırılmış" görünür.
- **Ayrılabilir arka planlar**: kişi ve nesneler **düz kroma yeşil (#00FF00)** üzerinde; ışık ve duman **saf siyah** üzerinde. Gölge, zemin, yazı, çerçeve olmasın.
- Mevcut en yüksek çözünürlükte üretin (2K / 4K). Ham görselleri `themes/<id>/assets/raw/` içinde (git'te değil), işlenmişleri `assets/` içinde tutun.
- Yapay zekâ araçları sağ alt köşeye sık sık bir işaret ekler: kitin işleme araçları bunu siler.
- Gerçek bir kişinin (merhumun) fotoğrafını veya benzerini kullanmak için yakınlarının izni gerekir; telifli görsel ve müzik kullanmayın.

## 1. Arka plan (9:16, 1080 × 1920)

**Yukarıdan aşağıya bantlar** olarak düşünün ve prompt'a yüksekliğin yüzdeleri olarak yazın, örneğin: %0–40 ana nesne (sahne, kürsü, tezgâh…), %40–60 süsler ve etkileşim noktaları, %60–100 kitin kalabalığı yerleştireceği **boş zemin**.

- Kamera yaklaşık 2–3 m yükseklikte, tam karşıdan, simetrik: perspektifi ölçmek kolay olur ve kalabalık doğal görünür.
- Arka planda **kimse olmasın** (kişileri kit ekler).
- Kişilerin yürümesi için **yeterli boş zemin** ve (gerekirse) ortada bir koridor bırakın.
- En güvenilir yol: basit bloklarla (ana nesne, sıralar, koridor) bir **yerleşim taslağı** çizip yapay zekâya *"Bu düz yerleşim taslağını fotogerçekçi bir görsele çevir, kompozisyonu, boyutları ve konumları aynen koru"* diyerek vermek.

```
Dikey 9:16 [fotoğraf / resim] [mekân], tam simetrik, tam karşıdan görünüm, kamera yaklaşık 3 metre yüksekte.
Üst %40: [ana nesne], büyük ve ortada.
%40 ile %60 arası: [süsler, etkileşim noktaları], simetrik.
Alt %40: ortasında [koridor / halı] olan boş [zemin malzemesi] zemin. Hiçbir yerde kimse yok.
[STYLE]
```

Elinize geçince: `/overlay?scene` açın ve kişiler zeminde doğru boyda duruncaya dek `scene.json` ayarlarını (ufuk, kişi boyu, zemin, koridor, engeller, koltuklar, çapa noktaları) düzenleyin.

## 2. Karakterler: tek animasyon sayfası

**Tek karakter yeter**: kit her kişi için onu sağa sola çevirir. **Tüm hareketlerin olduğu tek bir 16:9 görsel** üretin, ızgara halinde, satır başına bir hareket, soldan sağa çizgi film gibi ardışık kareler olarak okunacak şekilde.

**Temanın gerçekten kullandığı** hareketleri listeleyin: bekleme (zamanın %95'i), içeri yürüme (arkadan görünür), dışarı yürüme (kameraya dönük), yana yürüme ve hediye / sohbet komutu eylemleri.

```
Ekli referans görselin geçtiği mekânda geçen 2.5D bir canlı yayın oyunu için TEK karakterin TEK bir 16:9 animasyon model sayfasını (sprite sheet) oluştur (referansı yalnızca renk ve ışık için kullan).
KARAKTER: [karakter, kıyafet].
SANAT STİLİ: [arka planla aynı stil].
DÜZEN: tam olarak [N] adet AYNI karakterin çizimi, [sütun] sütun ve [satır] satırlık katı bir görünmez ızgarada, her biri kendi hücresinin ortasında ve çevresinde net boşluk var, ayaklar hücrenin alt çizgisinde, hepsi aynı ölçekte, aynı kamera hafif yukarıdan.
ARKA PLAN: tamamen düz saf kroma yeşil (#00FF00). Zemin yok, minder yok, gölge yok. KESİNLİKLE yazı, rakam, etiket veya ızgara çizgisi yok.
Satır 1: kameradan uzaklaşarak yürüme (arkadan görünüm), bacakları belirgin şekilde dönüşümlü 6 karelik yürüme döngüsü.
Satır 2: kameraya doğru yürüme, aynı yürüme döngüsü.
Satır 3: sağa yürüme (yan görünüm), aynı yürüme döngüsü.
Satır 4: [bekleme ve ana eylemin kareleri].
Satır 5: [diğer eylemler].
SON KONTROL: her hücrede aynı karakter ve ölçek; arka plan tamamen düz yeşil; yazı yok. Kontrollerden biri başarısızsa yeniden üret.
```

Sayfayı kesin (yapay zekâ ızgarayı bozsa bile her pozu bulur, yeşili siler, kaçak rakamları atar, pozlar arası göreli ölçeği korur):

```
pnpm assets:cut themes/<id>/assets/raw/character.png themes/<id>/assets/chars/character.png --auto --scale 0.7 --preview raw/check.png
```

Denetim görselini açın (kareler numaralıdır) ve `theme.json` → `characters` içinde tanımlayın: `sheet`, `frames`, `walkUp` / `walkDown` / `walkSide`, `poses`. Eksik kare için eğilmelerde `"idle@0.8"` (aşağı doğru basık) kullanın.

## 3. Efektler (siyah arka plan)

Haleler, ışınlar, duman, ışıltılar, havai fişek: **saf siyah** üzerinde üretin, nesne ortada ve kenarlara değmeden.

```
[efekt], ortada, saf siyah arka planda, görselde başka hiçbir şey yok, yazı yok. [STYLE]
```

```
pnpm assets:alpha themes/<id>/assets/raw/halo.jpg themes/<id>/assets/fx/halo.png --max 1024
```

Parlaklık opaklığa dönüşür: duman ve ışık sahnenin üstünde doğal yumuşaklığını korur. Bir eylem adımında `"image": "assets/fx/halo.png"` ile kullanın.

## 4. Eşyalar, simgeler

Yeşil üzerinde, görsel başına bir nesne (veya aralıklı nesnelerden oluşan bir sıra) üretin, `pnpm assets:cut ... --auto` ile kesin. Hediye kademesi simgeleri basit ve 40px'te okunur olmalıdır.

## 5. Ses

- **Ses efektleri** (`assets/sfx/<ad>.mp3`): **gerçek kayıtlar** kullanın, 0,5–5 saniye, sönümlenen. Telifsiz kaynaklar: Freesound (CC0 süzün), Pixabay Ses Efektleri. Kodla sentezlenen sesler genelde sahte ve sert çıkar.
- **Fon müziği** (`assets/music/*.mp3`): enstrümantal, yeterince uzun (birkaç dakika; kısa parçalar çok tekrarlanır), kullanım lisanslı.
- Dosyaları benzer ses seviyesine getirin; `theme.json` → `sounds` her ses için bekleme süresi tanımlar ki yoğun canlılar gürültülü olmasın.
- Her görselin kaynağını temanın `CREDITS.md` dosyasına yazın.

## 6. Yazı ve arayüz

- İzleyiciler telefondan izler: 1080px'lik çerçeve yaklaşık 1/3 boyutta görünür. **Yazı 20px veya üstü**, az yazı, kısa cümleler.
- Panelleri **güvenli bölgede** tutun (`/overlay?safe`): üstte 240px, her yanda 100px, sol alt yarı (yorum kutusu) örtülür veya kesilir.
- Sahnenin görünmesine izin veren yarı saydam paneller; ana nesneyi örtmeyin.
- Google Fonts'tan Türkçe karakterleri destekleyen yazı tipleri (Be Vietnam Pro, Lora, Playfair Display…).

## Önerilen sıra

1. Arka plan → `scene.json` ölçümü.
2. Tek karakter sayfası → kes → tanımla.
3. Hediye kademeleri için efektler.
4. Ses, müzik.
5. Arayüz: renkler ve metin `hud` içinde, ya da `theme.js` içinde kendi arayüzünüz.
