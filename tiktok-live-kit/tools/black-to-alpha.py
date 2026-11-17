"""Siyah arka planlı efekt görseli (ışık, duman, huzme) -> şeffaf arka planlı PNG, doğal solukluğu korur.

Çalıştırma (kit klasöründe, uv gerekir: https://docs.astral.sh/uv/):
    pnpm assets:alpha themes/<id>/assets/raw/halo.jpg themes/<id>/assets/fx/halo.png --max 1024

Parlaklık opaklığa dönüşür: tam siyah yerler tamamen şeffaf olur, parlak yerler rengini korur.
--corner 0.07: sağ alttaki bir köşe karesini siler (yapay zekâ araçlarının otomatik eklediği işaret için), 0 verilirse dokunmaz.
"""
import argparse

import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument('src')
ap.add_argument('out')
ap.add_argument('--max', type=int, default=0, help='küçültme sonrası en uzun kenar (0 = özgün boyut)')
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
alpha = np.clip((alpha - 6) / (255 - 6), 0, 1)  # siyaha yakın sıkıştırma gürültüsünü atar
safe = np.maximum(alpha, 1e-3)[..., None]
color = np.clip(rgb / 255 / safe, 0, 1)  # siyah karışımını atar ki arka plana konunca renk matlaşmasın
out = np.dstack([color * 255, alpha * 255]).astype(np.uint8)
Image.fromarray(out, 'RGBA').save(a.out, optimize=True)
print(f'{a.out}: {w}x{h}')
