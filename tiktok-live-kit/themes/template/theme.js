// Temaya özel kısım. Çoğu temanın bu dosyayı düzenlemesi gerekmez: her şey theme.json + scene.json içinde tanımlanır.
// Motorun hazır sunmadığı bir eylem ya da çizim katmanı gerektiğinde kullanılır.
//
//   Kit.action('fonksiyonAdi', (person, ev, ctx) => { ... })   theme.json'dan çağrılır: { "js": "fonksiyonAdi" }
//   Kit.on('frame', (t, dt) => { ... })                        her karede çalışır
//   Kit.on('gift', (ev) => { ... })                            olay dinler: join chat like gift command follow share title goal periodic speak seated
//
// Hazır araçlar: Kit.scene (kişiler, noktalar, kamera), Kit.fx (efektler), Kit.audio (ses), Kit.hud (arayüz), Kit.assets (görsel, gif, video)

// Örnek: büyük hediye gönderenin başının çevresine ekstra yıldız serpilir
// Kit.action('yildiz-sac', (person) => {
//   const h = Kit.scene.P.head(person);
//   Kit.fx.emit('star', { x: h.x, y: h.y, count: 20, spread: 40 });
// });
