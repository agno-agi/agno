// Phần riêng của theme. Phần lớn theme không cần sửa file này: mọi thứ khai báo trong theme.json + scene.json.
// Dùng khi muốn một hành động hay một lớp vẽ mà engine chưa có sẵn.
//
//   Kit.action('tenHam', (person, ev, ctx) => { ... })   gọi từ theme.json: { "js": "tenHam" }
//   Kit.on('frame', (t, dt) => { ... })                  chạy mỗi khung hình
//   Kit.on('gift', (ev) => { ... })                      nghe sự kiện: join chat like gift command follow share title goal periodic speak seated
//
// Công cụ có sẵn: Kit.scene (người, điểm, camera), Kit.fx (hiệu ứng), Kit.audio (tiếng), Kit.hud (giao diện), Kit.assets (ảnh, gif, video)

// Ví dụ: người tặng quà lớn được rắc thêm sao quanh đầu
// Kit.action('rac-sao', (person) => {
//   const h = Kit.scene.P.head(person);
//   Kit.fx.emit('star', { x: h.x, y: h.y, count: 20, spread: 40 });
// });
