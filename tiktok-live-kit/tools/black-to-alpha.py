"""Ảnh hiệu ứng nền đen (ánh sáng, khói, tia sáng) -> PNG nền trong suốt, giữ độ mờ tự nhiên.

Chạy (ở thư mục kit, cần uv: https://docs.astral.sh/uv/):
    pnpm assets:alpha themes/<id>/assets/raw/halo.jpg themes/<id>/assets/fx/halo.png --max 1024

Độ sáng thành độ đục: chỗ đen tuyệt đối trong suốt hẳn, chỗ sáng giữ nguyên màu.
--corner 0.07: xoá một góc vuông ở dưới bên phải (dấu ✦ Gemini / Flow tự chèn), đặt 0 để giữ nguyên.
"""
import argparse

import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument('src')
ap.add_argument('out')
ap.add_argument('--max', type=int, default=0, help='cạnh dài nhất sau khi thu nhỏ (0 = giữ cỡ gốc)')
ap.add_argument('--corner', type=float, default=0.07)
a = ap.parse_args()

im = Image.open(a.src).convert('RGB')
if a.max and max(im.size) > a.max:
    im.thumbnail((a.max, a.max), Image.LANCZOS)
rgb = np.asarray(im).astype(np.float32)
h, w, _ = rgb.shape
if a.corner > 0:
    s = int(min(w, h) * a.corner)
    rgb[h - s:, w - s:] = 0
alpha = rgb.max(axis=2)
alpha = np.clip((alpha - 6) / (255 - 6), 0, 1)  # bỏ nhiễu nén gần đen
safe = np.maximum(alpha, 1e-3)[..., None]
color = np.clip(rgb / 255 / safe, 0, 1)  # bỏ trộn đen để màu không xỉn khi đặt lên nền
out = np.dstack([color * 255, alpha * 255]).astype(np.uint8)
Image.fromarray(out, 'RGBA').save(a.out, optimize=True)
print(f'{a.out}: {w}x{h}')
