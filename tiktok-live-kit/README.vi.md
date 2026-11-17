# TikTok Live Kit

[English](README.md) | **Tiếng Việt**

Bộ khung chung để làm **game / overlay tương tác cho TikTok LIVE**. Người xem vào live, bình luận, thả tim, tặng quà thì nhân vật và hiệu ứng trên màn hình phản ứng theo.

Lõi viết một lần. Mỗi chủ đề (quán cà phê, sàn nhảy, hồ câu cá…) là một **theme** cắm vào thư mục `themes/`, đổi ngay trên bảng điều khiển.

Kit không kèm theme làm sẵn, chỉ có khung trống `themes/template` (2D) và `themes/template-3d` (3D, Three.js) để chép ra làm chủ đề của mình. Vẻ đẹp của theme đến từ asset (ảnh nền, nhân vật, GIF, video, nhạc) do bạn chuẩn bị.

| Tài liệu | Nội dung |
|---|---|
| [docs/IDEA.vi.md](docs/IDEA.vi.md) | Ý tưởng theme của bạn: các câu cần trả lời trước khi làm (không gian, người xem, quà, chat, giọng đọc, asset) |
| [docs/THEME.vi.md](docs/THEME.vi.md) | Làm theme: cấu trúc, `scene.json`, `theme.json`, hành động, giọng đọc, `theme.js` |
| [docs/ASSETS-GUIDE.vi.md](docs/ASSETS-GUIDE.vi.md) | Làm đẹp do đâu: ảnh nền, tờ nhân vật, hiệu ứng, âm thanh bằng AI tạo ảnh, công cụ xử lý |
| [docs/GO-LIVE.vi.md](docs/GO-LIVE.vi.md) | Lên live: LIVE Studio / OBS, TikFinity, kiểm tra trước giờ phát, lỗi hay gặp |
| [AGENTS.md](AGENTS.md) | Cho AI lập trình (Claude Code, Codex, Gemini…): bản đồ repo, lệnh, quy tắc (tiếng Anh, AI vẫn trả lời bạn bằng tiếng Việt) |
| [CHANGELOG.vi.md](CHANGELOG.vi.md) | Các thay đổi |

## Làm theme của bạn

1. **Ý tưởng trước.** Đọc [docs/IDEA.vi.md](docs/IDEA.vi.md): không gian là gì, người xem thành ai, quà nào làm gì, lệnh chat, câu đọc, đã có asset nào. Để trống cũng được, AI sẽ hỏi.
2. **Làm cùng AI.** Mở thư mục kit trong Claude Code / Codex / Cursor rồi nói: *"Đọc AGENTS.md rồi hỏi tôi ý tưởng theo docs/IDEA.vi.md để làm một theme mới."* AI hỏi vài câu một lần, tóm thành bản kế hoạch một trang, bạn đồng ý rồi mới bắt tay làm.
3. **Thử.** Chọn theme mới trên bảng điều khiển, thử ở tab **Thử nghiệm**, rồi lên live ([docs/GO-LIVE.vi.md](docs/GO-LIVE.vi.md)).

Khi kit đang chạy khung trống, bảng điều khiển hiện sẵn các bước này kèm câu lệnh để chép.

### Để theme ở repo riêng

Mỗi kênh live có thể là một repo riêng chỉ chứa theme và dữ liệu, gọi server của kit với ba biến môi trường:

| Biến | Ý nghĩa |
|---|---|
| `KIT_THEMES_DIR` | Thư mục chứa theme của bạn (ưu tiên hơn `themes/` của kit) |
| `KIT_DATA_DIR` | Nơi lưu luật đã chỉnh, phiên live, giọng đọc (mặc định `data/` của kit) |
| `KIT_CONFIG` | File cấu hình ghi đè `config.json` của kit (ví dụ `{"theme": "ten-theme"}`) |

```bat
set KIT_THEMES_DIR=%~dp0themes
set KIT_DATA_DIR=%~dp0data
set KIT_CONFIG=%~dp0config.json
node ..\tiktok-live-kit\src\server.js
```

## Hạ tầng khi live

```
TikTok LIVE ──> TikFinity Desktop ──ws://127.0.0.1:21213──┐
          └──> (dự phòng) kết nối trực tiếp ───────────────┤
                                                           ▼
                                    Lõi (Node, cổng 3939)
                                    lọc trùng · gom combo · luật quà · xếp hạng · danh hiệu · mục tiêu
                                                           │ WebSocket
                         ┌─────────────────────────────────┴───────────────┐
                Bảng điều khiển (/)                               Overlay theme (/overlay)
                                                                          │
                              LIVE Studio (quay cửa sổ overlay.bat) hoặc OBS (nguồn Browser)
```

## Chạy

Cần Node.js 20 trở lên.

- Windows: bấm đúp **`run.bat`** (tự cài thư viện, mở server và bảng điều khiển).
- Hoặc:
  ```bash
  pnpm install
  pnpm start
  ```

Mở http://localhost:3939/ để vào bảng điều khiển.

## Lên live

Ngắn gọn: chạy `run.bat` → mở TikFinity Desktop nối kênh → bảng điều khiển bấm **Kết nối** (nguồn **Tự động**) → chạy `overlay.bat` rồi trong LIVE Studio thêm nguồn **Quay màn hình cửa sổ** (hoặc OBS: nguồn Browser `http://localhost:3939/overlay`, 1080 × 1920). Từng bước và lỗi hay gặp: [docs/GO-LIVE.vi.md](docs/GO-LIVE.vi.md).

Mất mạng, TikFinity tắt hay phần mềm phát tải lại trang đều không cần thao tác lại:
- Lõi tự nối lại, giãn dần từ 2 đến 30 giây.
- Overlay tự nối lại và dựng lại đám đông đang có.
- Bảng xếp hạng được lưu xuống file, nên tắt mở server không mất.

## Bảng điều khiển

Năm tab, bên phải luôn có khung xem trước overlay và top 3 người tặng quà:

- **Live**: chọn nguồn, kết nối, xem trạng thái và "sự kiện cuối cách đây bao lâu" để biết luồng có đang chạy; cài đặt theme; nhật ký.
- **Luật** (sửa trên web, không cần code):
  - Ai được vào sân: mọi người, hoặc chỉ người chat từ khoá / tặng quà.
  - Bậc quà theo giá một món.
  - Quà riêng theo ID hoặc tên, có **thư viện quà** (ảnh, tên, giá) tự học các món đã gặp trên live: bấm một quà là thêm luật cho nó.
  - Lệnh chat có thời gian chờ.
  - Nút ▶ trên mỗi dòng cho xem hiệu ứng của dòng đó trước khi lưu.
- **Thử nghiệm**: người xem giả, thả đám đông (10 / 30 / 60 / 400 người, để thử máy có chịu nổi), tự chạy (vừa / đông / cực đông), nút quà chia theo giá (nhỏ / vừa / lớn), nút xem từng hiệu ứng của theme, đọc thử giọng. Sự kiện giả đi qua đúng đường ống như live thật.
- **Thống kê**: số liệu phiên, bảng xếp hạng kèm danh hiệu, tải **CSV** để tri ân, mục tiêu, nút **Phiên mới**.
- **Hướng dẫn**: lên live trong 4 bước, ba cách phát, các địa chỉ overlay hay dùng, lỗi hay gặp.

Đổi theme ngay khi đang chạy, overlay tự tải lại.

## Làm theme mới

Xem [docs/THEME.vi.md](docs/THEME.vi.md). Tóm tắt: chép `themes/template`, thả asset vào `assets/`, đo cảnh trong `scene.json`, rồi khai báo hành động cho từng mức quà trong `theme.json`. Cần hiệu ứng riêng thì viết thêm `theme.js`. Theme có thể là 2D (ảnh nền + tờ nhân vật) hoặc 3D (`"renderer": "3d"`: mô hình GLB, camera thật, ánh sáng; xem mục "Cảnh 3D" trong THEME.vi.md), hoặc tự vẽ bằng gì cũng được (DOM, Canvas). Game ngoài như Unity cũng nối được vào WebSocket `/ws` với `{"type":"hello","role":"overlay"}`.

## Cấu trúc

```
src/
  server.js            HTTP + WebSocket, phân quyền control/overlay, nạp theme
  core/
    normalize.js       dữ liệu thô của mọi nguồn → một dạng sự kiện chung
    streaks.js         gom quà combo (chỉ tính phần tăng, không cộng trùng)
    rules.js           luật: ID quà → tên quà → bậc giá; lệnh chat; từ khoá vào sân
    engine.js          đường ống: lọc trùng → combo → luật → phiên → phát sự kiện
    session.js         người chơi, xếp hạng, danh hiệu, mục tiêu, lưu file, xuất CSV
    gift-catalog.js    ghi nhớ quà đã gặp
    voice.js, tts.js   mẫu câu giọng đọc (lọc bình luận, giãn cách), đọc tiếng Việt, đọc sẵn câu cố định
    draws.js           bốc thăm qua chat (rút thăm, rút bài...)
  providers/           tikfinity · connector (trực tiếp) · demo · manager (nối lại, chuyển nguồn, canh im lặng)
public/
  control/             bảng điều khiển
  sdk/                 live-sdk (kết nối) · geometry · assets · fx · audio · scene (đám đông, camera) · hud · kit (chạy hành động JSON)
themes/<id>/           theme.json + scene.json + index.html + theme.js + assets/
data/                  (không vào git) settings, luật đã chỉnh, phiên live, danh sách quà
tools/                 xử lý asset: cut-sheet.py (pnpm assets:cut), black-to-alpha.py (pnpm assets:alpha)
test/                  pnpm test
run.bat, overlay.bat   chạy server; mở overlay thành cửa sổ Chrome cho LIVE Studio quay
```

## Cấu hình

`config.json` là cấu hình mặc định. Những gì đổi trên bảng điều khiển (kênh, nguồn, theme) được lưu riêng ở `data/settings.json`.

| Khoá | Ý nghĩa |
|---|---|
| `port`, `host` | Mặc định `127.0.0.1:3939`, chỉ máy này truy cập được. `host` nhận danh sách (`"127.0.0.1,192.168.137.1"`) để mở thêm đúng một địa chỉ (ví dụ điểm phát Wi-Fi của máy) |
| `allowLan` | `true` cho máy khác trong mạng LAN mở được (ví dụ điều khiển bằng điện thoại) |
| `provider` | `auto` \| `tikfinity` \| `connector` |
| `tikfinityUrl` | Mặc định `ws://127.0.0.1:21213/` |
| `autoConnect` | Tự kết nối khi server khởi động |
| `signApiKey` | Key Euler Stream nếu nguồn trực tiếp bị giới hạn lượt |
| `maxJoinsPerSecond` | Chặn ngập người vào khi live đông (mặc định 15/giây) |
| `playerTtlMinutes` | Im lặng quá bao lâu thì coi như đã rời sân |
| `watchdogSeconds` | Nguồn trực tiếp im quá lâu thì tự nối lại |

## Lưu ý

- Nguồn trực tiếp (`tiktok-live-connector`) là thư viện không chính thức. TikTok đổi giao thức thì chạy `pnpm update tiktok-live-connector`. Nên dùng TikFinity làm nguồn chính.
- Live đông thì TikTok không gửi đủ từng lượt vào phòng và từng lượt tim. Quà và bình luận thì gần như đủ.

## Giấy phép

[MIT](LICENSE). Kit là dự án độc lập, không liên kết hay được TikTok bảo trợ. Asset bạn đưa vào theme (ảnh, nhạc, font) theo giấy phép riêng của từng asset.
