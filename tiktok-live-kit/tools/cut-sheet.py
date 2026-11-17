"""Cắt tờ nhân vật dạng lưới (gen bằng AI, nền xanh lá) thành dải khung ngang cho Kit.

Chạy (ở thư mục kit, cần uv: https://docs.astral.sh/uv/):
    pnpm assets:cut themes/<id>/assets/raw/character.png themes/<id>/assets/chars/character.png --auto
    (tức là: uv run --no-project --with pillow --with numpy python tools/cut-sheet.py ...)
    tuỳ chọn: --cols 6 --rows 5 (mặc định đúng prompt master), --auto (AI xếp hàng không đều: tự dò từng dáng),
              --scale 0.66 (thu nhỏ tờ ra), --preview đường/dẫn.png (ảnh soát, mặc định cạnh file ra)

Làm gì:
  1. Tách nền: lấy màu nền ở viền ảnh (thường là xanh lá), xoá phần cùng màu, viền mềm, khử ánh xanh hắt lên áo.
  2. Chia đều lưới cột x hàng (hoặc --auto: tìm khoảng trống giữa các hàng rồi giữa các dáng), mỗi ô giữ lại người,
     bỏ số thứ tự, chữ, chấm lẻ.
  3. Xếp các khung thành một hàng ngang theo thứ tự đọc (trái sang phải, trên xuống dưới), canh chân chung một đáy,
     GIỮ NGUYÊN tỉ lệ giữa các khung (người quỳ thấp hơn người đứng) để code vẽ đúng cỡ.
  4. Ghi thêm <tên>-preview.png có đánh số khung để soát.
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
    lo, hi = 60.0, 140.0  # gần màu nền hơn lo: trong suốt; xa hơn hi: giữ nguyên; ở giữa: viền mềm
    alpha = np.clip((dist - lo) / (hi - lo), 0, 1)
    out = rgb.astype(np.float32)
    if bg[1] > bg[0] + 40 and bg[1] > bg[2] + 40:  # nền xanh lá: khử ánh xanh hắt lên người
        cap = np.maximum(out[..., 0], out[..., 2])
        out[..., 1] = np.minimum(out[..., 1], cap + 8)
    return out.astype(np.uint8), (alpha * 255).astype(np.uint8), bg


def keep_figure(alpha):
    """Giữ mảng lớn nhất (người) và các mảng đáng kể nằm sát nó; bỏ số thứ tự, chữ, chấm lẻ AI hay vẽ thêm."""
    m = alpha > 40
    h, w = m.shape
    label = np.zeros((h, w), np.int32)
    comps = []  # (diện tích, x0, y0, x1, y1)
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
    """Các đoạn liên tiếp có counts >= min_count, nối đoạn cách nhau < max_gap, bỏ đoạn ngắn hơn min_len."""
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
    """Cắt luân phiên ngang / dọc theo khoảng trống cho tới khi mỗi mảnh chỉ còn một dáng (XY-cut).
    Trả về các vùng theo thứ tự đọc: từng hàng từ trên xuống, trong hàng từ trái sang phải."""
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
    med = float(np.median([r[4] for r in regions]))  # bỏ mảnh quá nhỏ (dấu bản quyền, chấm lẻ)
    regions = [r[:4] for r in regions if r[4] >= 0.15 * med]
    # gom thành hàng theo đáy (chân) gần nhau, rồi xếp trái sang phải
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
    if alpha.min() == 255:  # ảnh không có nền trong suốt: tách theo màu nền
        rgb, alpha, bg = key_background(rgb)
        print(f'Tách nền màu {tuple(int(v) for v in bg)}')
    H, W = alpha.shape
    if a.auto:
        rows = auto_regions(alpha)
        regions = [r for row in rows for r in row]
        print(f'Tự dò: {len(rows)} hàng, số dáng mỗi hàng {[len(row) for row in rows]}')
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
        sys.exit('Không thấy nhân vật nào. Kiểm tra nền và số cột / hàng.')
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

    print(f'{len(frames)} khung, mỗi khung {fw}x{fh}px -> {a.out}')
    print(f'Xem soát: {prev_path}')
    if empty:
        print(f'Ô trống (không thấy người): {empty}')
    if a.cols == 6 and a.rows == 5 and not a.auto:
        print('Khai báo trong theme.json "characters" (đúng thứ tự prompt master):')
        print(json.dumps({
            'sheet': a.out.replace('\\', '/'), 'frames': 30,
            'walkUp': [0, 1, 2, 3, 4, 5], 'walkDown': [6, 7, 8, 9, 10, 11], 'walkSide': [12, 13, 14, 15, 16, 17],
            'poses': {'idle': 18, 'handsUp': 19, 'bowHalf': 20, 'bowHands': 21, 'bowFull': 22, 'idle2': 23,
                      'stand': 24, 'sitDown': 25, 'incense': 26, 'offer': 27, 'xam': 28, 'xam2': 29},
        }, ensure_ascii=False))


if __name__ == '__main__':
    main()
