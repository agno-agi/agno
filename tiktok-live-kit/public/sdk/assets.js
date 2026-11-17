// Kit.assets: nạp asset mọi định dạng về một kiểu "drawable" vẽ được lên canvas.
//   ảnh: png / jpg / webp      GIF động: gif (giải mã từng khung, cần trình duyệt có ImageDecoder)
//   video: mp4 / webm (webm có nền trong suốt)      Lottie: json (cần /vendor/lottie.min.js)
//
//   const d = Kit.assets.get('assets/fx/halo.png');   // dùng ngay, vẽ khi đã sẵn sàng
//   d.draw(ctx, x, y, w, h, { t, alpha, flip })       // t: thời gian (ms) để chạy GIF / Lottie
//   const s = Kit.assets.sheet('assets/chars/ba.png', 5) // tờ khung hình chia đều theo chiều ngang
//   s.drawFrame(ctx, i, cx, baseY, height, { flip })     // vẽ khung i, neo chân tại (cx, baseY)
//
// Asset thiếu: d.missing = true, người gọi tự vẽ hình giữ chỗ.

(function () {
  const cache = new Map();
  const extOf = (url) => (String(url).split('?')[0].match(/\.([a-z0-9]+)$/i)?.[1] || '').toLowerCase();

  function base(url) {
    return { url, kind: 'none', ready: false, missing: false, w: 0, h: 0, draw() {} };
  }

  function image(url) {
    const d = base(url);
    d.kind = 'image';
    const img = new Image();
    img.onload = () => { d.ready = true; d.w = img.naturalWidth; d.h = img.naturalHeight; d.img = img; };
    img.onerror = () => { d.missing = true; };
    img.src = url;
    d.draw = (ctx, x, y, w, h, o = {}) => {
      if (!d.ready) return;
      drawWith(ctx, img, 0, 0, d.w, d.h, x, y, w ?? d.w, h ?? d.h, o);
    };
    return d;
  }

  // GIF: giải mã thành danh sách khung + thời lượng; trình duyệt không hỗ trợ thì dùng khung đầu
  function gif(url) {
    const d = base(url);
    d.kind = 'gif';
    d.frames = [];
    (async () => {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(res.status);
        if (!('ImageDecoder' in window)) throw new Error('no ImageDecoder');
        const dec = new ImageDecoder({ data: res.body, type: 'image/gif' });
        await dec.tracks.ready;
        const n = dec.tracks.selectedTrack.frameCount;
        let total = 0;
        for (let i = 0; i < n; i++) {
          const { image: frame } = await dec.decode({ frameIndex: i });
          const ms = Math.max(20, (frame.duration || 100000) / 1000);
          const bmp = await createImageBitmap(frame);
          frame.close();
          d.frames.push({ bmp, start: total, ms });
          total += ms;
        }
        d.total = total;
        d.w = d.frames[0].bmp.width; d.h = d.frames[0].bmp.height;
        d.ready = true;
      } catch {
        const fallback = image(url);
        const wait = setInterval(() => {
          if (fallback.missing) { d.missing = true; clearInterval(wait); }
          if (fallback.ready) { Object.assign(d, { w: fallback.w, h: fallback.h, frames: [{ bmp: fallback.img, start: 0, ms: 1e9 }], total: 1e9, ready: true }); clearInterval(wait); }
        }, 100);
      }
    })();
    d.frameAt = (t = performance.now()) => {
      if (!d.ready) return null;
      const k = t % d.total;
      return d.frames.find((f) => k >= f.start && k < f.start + f.ms) || d.frames[0];
    };
    d.draw = (ctx, x, y, w, h, o = {}) => {
      const f = d.frameAt(o.t);
      if (f) drawWith(ctx, f.bmp, 0, 0, d.w, d.h, x, y, w ?? d.w, h ?? d.h, o);
    };
    return d;
  }

  function video(url) {
    const d = base(url);
    d.kind = 'video';
    const v = document.createElement('video');
    Object.assign(v, { muted: true, loop: true, playsInline: true, autoplay: true, preload: 'auto' });
    v.crossOrigin = 'anonymous';
    v.oncanplay = () => { d.ready = true; d.w = v.videoWidth; d.h = v.videoHeight; v.play().catch(() => {}); };
    v.onerror = () => { d.missing = true; };
    v.src = url;
    d.el = v;
    d.draw = (ctx, x, y, w, h, o = {}) => { if (d.ready) drawWith(ctx, v, 0, 0, d.w, d.h, x, y, w ?? d.w, h ?? d.h, o); };
    return d;
  }

  let lottieLib = null;
  function loadLottieLib() {
    if (window.lottie) return Promise.resolve(window.lottie);
    lottieLib ||= new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = '/vendor/lottie.min.js';
      s.onload = () => resolve(window.lottie);
      s.onerror = reject;
      document.head.appendChild(s);
    });
    return lottieLib;
  }

  function lottieAnim(url) {
    const d = base(url);
    d.kind = 'lottie';
    (async () => {
      try {
        const [lib, data] = await Promise.all([loadLottieLib(), fetch(url).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })]);
        const box = document.createElement('div');
        box.style.cssText = `position:fixed;left:-99999px;top:0;width:${data.w}px;height:${data.h}px`;
        document.body.appendChild(box);
        d.anim = lib.loadAnimation({ container: box, renderer: 'canvas', loop: true, autoplay: true, animationData: data });
        d.w = data.w; d.h = data.h;
        d.canvas = () => box.querySelector('canvas');
        d.ready = true;
      } catch { d.missing = true; }
    })();
    d.draw = (ctx, x, y, w, h, o = {}) => { const c = d.ready && d.canvas(); if (c) drawWith(ctx, c, 0, 0, c.width, c.height, x, y, w ?? d.w, h ?? d.h, o); };
    return d;
  }

  function drawWith(ctx, src, sx, sy, sw, sh, x, y, w, h, o) {
    const needSave = o.alpha != null || o.flip || o.blend;
    if (needSave) {
      ctx.save();
      if (o.alpha != null) ctx.globalAlpha *= o.alpha;
      if (o.blend) ctx.globalCompositeOperation = o.blend;
      if (o.flip) { ctx.translate(x + w, y); ctx.scale(-1, 1); x = 0; y = 0; }
    }
    ctx.drawImage(src, sx, sy, sw, sh, x, y, w, h);
    if (needSave) ctx.restore();
  }

  /** Drawable cho một đường dẫn bất kỳ (tự nhận định dạng theo đuôi file). */
  function get(url) {
    if (!url) { const d = base(''); d.missing = true; return d; }
    if (cache.has(url)) return cache.get(url);
    const ext = extOf(url);
    const d = ext === 'gif' ? gif(url) : ext === 'mp4' || ext === 'webm' ? video(url) : ext === 'json' ? lottieAnim(url) : image(url);
    cache.set(url, d);
    return d;
  }

  // ---------- Tờ khung hình (nhân vật nhiều tư thế) ----------
  // Chia đều theo chiều ngang thành `frames` ô; mỗi ô tự cắt sát phần có hình (bỏ khoảng trống)
  // để nhân vật các tư thế đứng chân thẳng hàng và cao đều nhau.
  function sheet(url, frames = 1) {
    const key = `${url}#${frames}`;
    if (cache.has(key)) return cache.get(key);
    const src = get(url);
    const s = { url, frames, ready: false, missing: false, boxes: [], src };
    const prepare = () => {
      if (src.missing) { s.missing = true; return; }
      if (!src.ready) return void setTimeout(prepare, 80);
      const fw = src.w / frames, fh = src.h;
      s.frameW = fw; s.frameH = fh;
      if (src.kind === 'image') {
        const c = document.createElement('canvas');
        c.width = src.w; c.height = src.h;
        const g = c.getContext('2d', { willReadFrequently: true });
        g.drawImage(src.img, 0, 0);
        let data = null;
        try { data = g.getImageData(0, 0, c.width, c.height).data; } catch {}
        for (let i = 0; i < frames; i++) s.boxes.push(data ? trim(data, c.width, Math.round(i * fw), 0, Math.round(fw), fh) : { x: i * fw, y: 0, w: fw, h: fh });
      } else {
        for (let i = 0; i < frames; i++) s.boxes.push({ x: i * fw, y: 0, w: fw, h: fh });
      }
      s.ready = true;
    };
    prepare();
    // vẽ khung i, neo giữa chân tại (cx, baseY), cao `height` (theo chiều cao của ô đã cắt)
    s.drawFrame = (ctx, i, cx, baseY, height, o = {}) => {
      if (!s.ready) return false;
      const b = s.boxes[Math.max(0, Math.min(frames - 1, i | 0))];
      const k = height / (o.refH || b.h);
      const w = b.w * k, h = b.h * k;
      const img = src.kind === 'gif' ? src.frameAt(o.t)?.bmp : src.kind === 'video' ? src.el : src.img;
      if (!img) return false;
      drawWith(ctx, img, b.x, b.y, b.w, b.h, cx - w / 2, baseY - h, w, h, o);
      return true;
    };
    cache.set(key, s);
    return s;
  }

  // Hộp bao phần có alpha > 16 trong vùng (x0, y0, w, h)
  function trim(data, W, x0, y0, w, h) {
    let minX = w, minY = h, maxX = -1, maxY = -1;
    for (let y = 0; y < h; y += 2) {
      for (let x = 0; x < w; x += 2) {
        if (data[((y0 + y) * W + (x0 + x)) * 4 + 3] > 16) {
          if (x < minX) minX = x; if (x > maxX) maxX = x;
          if (y < minY) minY = y; if (y > maxY) maxY = y;
        }
      }
    }
    if (maxX < 0) return { x: x0, y: y0, w, h };
    return { x: x0 + minX, y: y0 + minY, w: maxX - minX + 2, h: maxY - minY + 2 };
  }

  window.Kit = window.Kit || {};
  window.Kit.assets = { get, sheet, extOf };
})();
