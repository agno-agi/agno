// Anma teması: özel parçacıklar. Görsel/ses dosyası kullanılmaz; hepsi canvas ile çizilir (telif sorunu yok).
// "mum": yukarı süzülen sıcak alev kıvılcımı, "karanfil": yavaş düşen kırmızı/beyaz yaprak, "nur": yumuşak beyaz ışık.
(function () {
  Kit.fx.preset('mum', { life: [1600, 2600], size: [4, 8], vy: [-70, -30], vx: [-12, 12], sway: 10, alpha: 0.95, shape: 'dot', color: '255,196,110', glow: true, blend: 'lighter', twinkle: true });
  Kit.fx.preset('karanfil', { life: [5000, 8000], size: [9, 15], vy: [60, 120], vx: [-25, 25], sway: 35, spin: [-1.5, 1.5], alpha: 0.95, shape: 'petal', palette: ['190,30,50', '225,225,225', '160,25,45', '245,235,230'] });
  Kit.fx.preset('nur', { life: [2400, 4200], size: [3, 6], vy: [-30, -8], vx: [-10, 10], sway: 14, alpha: 0.9, shape: 'dot', color: '255,248,225', glow: true, blend: 'lighter', twinkle: true });
})();
