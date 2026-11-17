# Thả asset của theme vào đây

[English](README.md) | **Tiếng Việt**

Khung trống không kèm ảnh, nhạc hay tiếng nào. Thiếu asset thì engine vẽ hình khối giữ chỗ. Đẹp hay không là do asset bạn chuẩn bị, xem `docs/ASSETS-GUIDE.vi.md` của kit để biết kiếm ở đâu hoặc gen bằng AI thế nào.

| Chỗ thả | Dùng cho | Khai báo ở |
|---|---|---|
| `background.jpg` (hoặc `.png`, `.webp`) | ảnh nền 1080×1920 | `scene.json` → `background` |
| `background.mp4` / `.webm` | video nền lặp (tuỳ chọn, đẹp hơn ảnh) | `scene.json` → `backgroundVideo` |
| `chars/*.png` | tờ nhân vật nhiều tư thế, nền trong suốt | `theme.json` → `characters` |
| `chars/*.gif` / `*.webm` | nhân vật động sẵn (nhảy, đi...) | `theme.json` → `characters[].idleAnim` |
| `fx/*.png` / `*.gif` / `*.webm` / `*.json` (Lottie) | ảnh hiệu ứng | bước `{ "fx": "sprite", "image": ... }` hoặc `image` của hạt |
| `sfx/<ten>.mp3` | tiếng hiệu ứng, gọi bằng tên | bước `{ "sound": "<ten>" }`; `sfx/like.mp3` tự kêu khi thả tim |
| `music/*.mp3` | nhạc nền, phát lặp theo danh sách | tự nạp |
| `ui/panel.png` | khung bảng giao diện | `theme.json` → `hud.panelImage` |

Ghi nguồn và giấy phép của từng asset vào `CREDITS.md` của theme.
