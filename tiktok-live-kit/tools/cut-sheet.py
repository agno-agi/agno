"""Izgara biçimindeki karakter sayfasını (yapay zekâyla üretilmiş, yeşil arka planlı) Kit için yatay kare şeridine keser.

Çalıştırma (kit klasöründe, uv gerekir: https://docs.astral.sh/uv/):
    pnpm assets:cut themes/<id>/assets/raw/character.png themes/<id>/assets/chars/character.png --auto
    (yani: uv run --no-project --with pillow --with numpy python tools/cut-sheet.py ...)
    seçenekler: --cols 6 --rows 5 (varsayılan ana prompt'a göre), --auto (YZ sıraları düzensiz dizdiyse her figürü kendisi bulur),
              --scale 0.66 (sayfayı küçültür), --preview yol/dosya.png (denetim görseli, varsayılan çıktının yanına)

Ne yapar:
  1. Arka planı ayırır: görselin kenarındaki rengi (genelde yeşil) alır, aynı rengi siler, kenarı yumuşatır, elbiseye vuran yeşil yansımayı giderir.
  2. Sütun x satır ızgarasına eşit böler (veya --auto: önce satırlar, sonra figürler arasındaki boşlukları bulur), her hücrede kişiyi tutar,
     sıra numarası, yazı, tek tek lekeler atılır.
  3. Kareleri okuma sırasıyla (soldan sağa, yukarıdan aşağı) tek yatay şeride dizer, ayakları ortak tabana hizalar,
     kareler arası ORANI KORUR (diz çöken kişi ayaktakinden kısadır) ki kod doğru boyda çizsin.
  4. Ayrıca kareleri numaralı <ad>-preview.png denetim görselini yazar.
"""
import argparse
import json
import sys

import numpy as np
from PIL import Image, ImageDraw


def key_background(rgb):
    h, w, _ = rgb.shape
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(np.float32)
    bg = np.median(border, axis=0)
    dist = np.sqrt(((rgb.astype(np.float32) - bg) ** 2).sum(axis=2))
    lo, hi = 60.0, 140.0  # arka plan rengine lo'dan yakınsa: şeffaf; hi'den uzaksa: olduğu gibi; arası: yumuşak kenar
    alpha = np.clip((dist - lo) / (hi - lo), 0, 1)
    out = rgb.astype(np.float32)
    if bg[1] > bg[0] + 40 and bg[1] > bg[2] + 40:  # yeşil arka plan: kişiye vuran yeşil yansımayı giderir
        cap = np.maximum(out[..., 0], out[..., 2])
        out[..., 1] = np.minimum(out[..., 1], cap + 8)
    return out.astype(np.uint8), (alpha * 255).astype(np.uint8), bg


def keep_figure(alpha):
    """En büyük parçayı (kişi) ve ona bitişik önemli parçaları tutar; YZ'nin sık eklediği sıra numarası, yazı, tek lekeleri atar."""
    m = alpha > 40
    h, w = m.shape
    label = np.zeros((h, w), np.int32)
    comps = []  # (alan, x0, y0, x1, y1)
    for sy, sx in zip(*np.nonzero(m)):
        if label[sy, sx]:
            continue
        n = len(comps) + 1
        label[sy, sx] = n
        stack, area, x0, y0, x1, y1 = [(sy, sx)], 0, sx, sy, sx, sy
        while stack:
            y, x = stack.pop()
            area += 1
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and m[ny, nx] and not label[ny, nx]:
                    label[ny, nx] = n
                    stack.append((ny, nx))
        comps.append((area, x0, y0, x1, y1))
    if not comps:
        return alpha
    big = max(range(len(comps)), key=lambda i: comps[i][0])
    _, bx0, by0, bx1, by1 = comps[big]
    pad = 0.15 * max(bx1 - bx0, by1 - by0)
    keep = np.zeros(len(comps) + 1, bool)
    for i, (area, x0, y0, x1, y1) in enumerate(comps):
        near = x1 >= bx0 - pad and x0 <= bx1 + pad and y1 >= by0 - pad and y0 <= by1 + pad
        if i == big or (near and area >= 0.02 * comps[big][0]):
            keep[i + 1] = True
    return np.where(keep[label] | (alpha <= 40) & (alpha > 0) & ~m, alpha, 0).astype(np.uint8)


def runs(counts, min_count, max_gap, min_len):
    """counts >= min_count olan ardışık aralıklar; aralarındaki boşluk < max_gap ise birleştirilir, min_len'den kısa olanlar atılır."""
    on = np.where(counts >= min_count)[0]
    if not len(on):
        return []
    segs, start, prev = [], on[0], on[0]
    for v in on[1:]:
        if v - prev > max_gap:
            segs.append((start, prev + 1))
            start = v
        prev = v
    segs.append((start, prev + 1))
    return [(a, b) for a, b in segs if b - a >= min_len]


def auto_regions(alpha):
    """Her parçada tek figür kalana dek boşluklardan dönüşümlü yatay / dikey keser (XY-cut).
    Bölgeleri okuma sırasıyla döndürür: satırlar yukarıdan aşağı, satır içinde soldan sağa."""
    m = alpha > 40
    H, W = m.shape
    min_h, min_w = H // 40, W // 120

    def split(x0, y0, x1, y1, horizontal, depth):
        sub = m[y0:y1, x0:x1]
        if horizontal:
            parts = [(x0, y0 + a, x1, y0 + b) for a, b in runs(sub.sum(axis=1), 2, 2, min_h)]
        else:
            parts = [(x0 + a, y0, x0 + b, y1) for a, b in runs(sub.sum(axis=0), 2, 3, min_w)]
        if len(parts) <= 1:
            if depth > 0:
                return [(x0, y0, x1, y1)] if parts else []
            return split(x0, y0, x1, y1, not horizontal, depth + 1) if parts else []
        out = []
        for p in parts:
            out += split(*p, not horizontal, 0)
        return out

    regions = [r + (int(m[r[1]:r[3], r[0]:r[2]].sum()),) for r in split(0, 0, W, H, True, 0)]
    if not regions:
        return []
    med = float(np.median([r[4] for r in regions]))  # çok küçük parçaları atar (telif işareti, tek lekeler)
    regions = [r[:4] for r in regions if r[4] >= 0.15 * med]
    # tabanı (ayakları) yakın olanları satır yapar, sonra soldan sağa dizer
    regions.sort(key=lambda r: r[3])
    rows, cur = [], []
    for r in regions:
        if cur and r[3] - cur[-1][3] > H / 16:
            rows.append(cur)
            cur = []
        cur.append(r)
    if cur:
        rows.append(cur)
    return [sorted(row, key=lambda r: r[0]) for row in rows]


def bbox(alpha, min_px=3):
    m = alpha > 40
    cols = np.where(m.sum(axis=0) >= min_px)[0]
    rows = np.where(m.sum(axis=1) >= min_px)[0]
    if not len(cols) or not len(rows):
        return None
    return cols[0], rows[0], cols[-1] + 1, rows[-1] + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('out')
    ap.add_argument('--cols', type=int, default=6)
    ap.add_argument('--rows', type=int, default=5)
    ap.add_argument('--auto', action='store_true')
    ap.add_argument('--scale', type=float, default=1.0)
    ap.add_argument('--preview')
    a = ap.parse_args()

    im = Image.open(a.src).convert('RGBA')
    arr = np.array(im)
    rgb, alpha = arr[..., :3], arr[..., 3]
    if alpha.min() == 255:  # görselde şeffaf arka plan yok: arka plan rengine göre ayırır
        rgb, alpha, bg = key_background(rgb)
        print(f'Arka plan rengi ayrıldı {tuple(int(v) for v in bg)}')
    H, W = alpha.shape
    if a.auto:
        rows = auto_regions(alpha)
        regions = [r for row in rows for r in row]
        print(f'Otomatik tespit: {len(rows)} satır, satır başına figür sayısı {[len(row) for row in rows]}')
    else:
        cw, ch = W / a.cols, H / a.rows
        regions = [(round(c * cw), round(r * ch), round((c + 1) * cw), round((r + 1) * ch)) for r in range(a.rows) for c in range(a.cols)]

    frames, empty = [], []
    for x0, y0, x1, y1 in regions:
        alpha[y0:y1, x0:x1] = keep_figure(alpha[y0:y1, x0:x1])
        b = bbox(alpha[y0:y1, x0:x1])
        i = len(frames)
        if not b:
            empty.append(i)
            frames.append(None)
            continue
        bx0, by0, bx1, by1 = b
        crop = np.dstack([rgb[y0 + by0:y0 + by1, x0 + bx0:x0 + bx1], alpha[y0 + by0:y0 + by1, x0 + bx0:x0 + bx1]])
        frames.append(Image.fromarray(crop, 'RGBA'))

    if a.scale != 1:
        frames = [f.resize((max(1, round(f.width * a.scale)), max(1, round(f.height * a.scale))), Image.LANCZOS) if f else None for f in frames]
    real = [f for f in frames if f]
    if not real:
        sys.exit('Hiç karakter bulunamadı. Arka planı ve sütun / satır sayısını kontrol edin.')
    fw = max(f.width for f in real) + 12
    fh = max(f.height for f in real) + 6
    strip = Image.new('RGBA', (fw * len(frames), fh), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        if f:
            strip.paste(f, (i * fw + (fw - f.width) // 2, fh - f.height - 3), f)
    strip.save(a.out, optimize=True)

    prev = Image.new('RGBA', strip.size, (40, 26, 20, 255))
    prev.alpha_composite(strip)
    d = ImageDraw.Draw(prev)
    for i in range(len(frames)):
        d.rectangle([i * fw, 0, (i + 1) * fw - 1, fh - 1], outline=(255, 210, 120, 160))
        d.text((i * fw + 6, 4), str(i), fill=(255, 240, 200, 255))
    prev_path = a.preview or a.out.rsplit('.', 1)[0] + '-preview.png'
    prev.convert('RGB').save(prev_path)

    print(f'{len(frames)} kare, her kare {fw}x{fh}px -> {a.out}')
    print(f'Denetim görseli: {prev_path}')
    if empty:
        print(f'Boş hücreler (kişi bulunamadı): {empty}')
    if a.cols == 6 and a.rows == 5 and not a.auto:
        print('theme.json "characters" içine ekleyin (ana prompt sırasıyla):')
        print(json.dumps({
            'sheet': a.out.replace('\\', '/'), 'frames': 30,
            'walkUp': [0, 1, 2, 3, 4, 5], 'walkDown': [6, 7, 8, 9, 10, 11], 'walkSide': [12, 13, 14, 15, 16, 17],
            'poses': {'idle': 18, 'handsUp': 19, 'bowHalf': 20, 'bowHands': 21, 'bowFull': 22, 'idle2': 23,
                      'stand': 24, 'sitDown': 25, 'incense': 26, 'offer': 27, 'xam': 28, 'xam2': 29},
        }, ensure_ascii=False))


if __name__ == '__main__':
    main()
