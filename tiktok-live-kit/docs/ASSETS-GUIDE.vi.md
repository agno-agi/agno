# Làm đẹp do đâu

[English](ASSETS-GUIDE.md) | **Tiếng Việt**

Kit lo chuyển động, hiệu ứng, giọng đọc, luật chơi. **Cái đẹp đến từ asset**: ảnh nền, nhân vật, hiệu ứng, âm thanh. Kit không kèm asset nào; tài liệu này chỉ cách tự chuẩn bị, chủ yếu bằng AI tạo ảnh (GPT Image, Gemini / Flow, Midjourney…).

```
Lớp 4  Giao diện: bảng, thẻ, chữ                 ← CSS trong theme.js hoặc hud có sẵn
Lớp 3  Hiệu ứng: hào quang, khói, tia sáng, hạt  ← ảnh nền đen → trong suốt
Lớp 2  Nhân vật, đạo cụ                          ← tờ hoạt hình nền xanh → cắt khung
Lớp 1  Ảnh nền                                   ← quan trọng nhất, quyết định 70% cảm giác
```

## Quy tắc chung

- **Một vibe cho cả bộ**: gen ảnh nền trước, rồi đưa chính ảnh nền làm ảnh tham chiếu cho mọi asset sau (*"match the colors and lighting of this image"*). Dùng chung một khối mô tả phong cách (STYLE) dán cuối mọi prompt.
- **Cùng kiểu vẽ**: nền ảnh thật thì nhân vật nên ảnh thật / 3D; nền vẽ thì nhân vật vẽ cùng nét. Lệch kiểu là thấy "dán đè" ngay.
- **Nền tách được**: người và đồ vật trên **nền xanh lá trơn (#00FF00)**; ánh sáng, khói trên **nền đen tuyệt đối**. Không đổ bóng, không sàn, không chữ, không khung.
- Gen độ phân giải cao nhất có thể (2K / 4K). Ảnh thô để trong `themes/<id>/assets/raw/` (không vào git), ảnh đã xử lý để ở `assets/`.
- Công cụ AI hay tự chèn dấu ✦ ở góc dưới phải: công cụ xử lý của kit xoá được.

## 1. Ảnh nền (9:16, 1080 × 1920)

Nghĩ theo **tầng từ trên xuống** rồi viết vào prompt bằng phần trăm chiều cao, ví dụ: 0–40% vật chính (sân khấu, bàn thờ, quầy…), 40–60% đồ trang trí và điểm tương tác, 60–100% **sàn trống** để kit đặt đám đông.

- Máy đặt cao khoảng 2–3m, nhìn thẳng, đối xứng: kit tính phối cảnh dễ và đám đông trông tự nhiên.
- **Không có người** trong ảnh nền (kit tự thêm người).
- Chừa **sàn trống đủ rộng** và (nếu có) một lối giữa để người đi vào.
- Chắc ăn nhất: vẽ một **bản phác bố cục** bằng hình khối đơn giản (khối vật chính, hàng ghế, lối đi), đưa cho AI kèm câu *"Turn this flat layout sketch into a photorealistic image, keep exactly the same composition, sizes and positions"*.

```
Vertical 9:16 [ảnh thật / tranh vẽ] of [không gian], perfectly symmetrical, straight-on view, camera about 3 meters high.
Top 40%: [vật chính], large and centered.
From 40% to 60%: [đồ trang trí, điểm tương tác], symmetrical.
Bottom 40%: empty [chất liệu sàn] floor with [lối đi / thảm] down the center. No people anywhere.
[STYLE]
```

Có ảnh rồi: mở `/overlay?scene`, chỉnh `scene.json` (chân trời, cỡ người, sàn, lối đi, vật cản, chỗ ngồi, điểm mốc) tới khi người đứng đúng sàn, đúng cỡ.

## 2. Nhân vật: một tờ hoạt hình

**Một nhân vật là đủ**: kit tự lật trái phải cho từng người. Gen **một ảnh 16:9 chứa mọi động tác**, chia lưới, mỗi hàng một động tác, đọc trái sang phải là các khung nối tiếp như phim hoạt hình.

Liệt kê động tác theo **những gì theme dùng**: dáng chờ (95% thời gian), đi vào (thấy lưng), đi ra (thấy mặt), đi ngang, và các hành động của quà / lệnh chat.

```
Create ONE 16:9 animation model sheet (sprite sheet) of a single character for a 2.5D live-stream game set in the place of the attached reference image (use it only for colors and lighting).
CHARACTER: [mô tả nhân vật, trang phục].
ART STYLE: [cùng kiểu với ảnh nền].
LAYOUT: exactly [N] drawings of the SAME character in a strict invisible grid of [cột] columns and [hàng] rows, each centered in its own cell with clear empty space around it, feet on the bottom line of the cell, all at the same scale, same camera slightly above.
BACKGROUND: perfectly flat pure chroma green (#00FF00). No floor, no cushion, no shadow. ABSOLUTELY NO text, numbers, labels or grid lines.
Row 1: walking away from the camera (seen from behind), 6-frame walk cycle with clearly alternating legs.
Row 2: walking toward the camera, same walk cycle.
Row 3: walking to the right (side view), same walk cycle.
Row 4: [dáng chờ và các khung của hành động chính].
Row 5: [các hành động khác].
FINAL CHECK: same character and scale in every cell; background perfectly flat green; no text. Regenerate if any check fails.
```

Cắt tờ (tự dò từng dáng kể cả khi AI xếp lệch lưới, tách nền xanh, bỏ chữ số lẻ, giữ đúng tỉ lệ giữa các dáng):

```
pnpm assets:cut themes/<id>/assets/raw/nhanvat.png themes/<id>/assets/chars/nhanvat.png --auto --scale 0.7 --preview raw/soat.png
```

Mở ảnh soát (có đánh số khung) rồi khai báo trong `theme.json` → `characters`: `sheet`, `frames`, `walkUp` / `walkDown` / `walkSide`, `poses`. Động tác thiếu khung thì dùng kiểu `"idle@0.8"` (nén thấp) cho cúi chào.

## 3. Hiệu ứng (nền đen)

Hào quang, tia sáng, khói, lấp lánh, pháo: gen trên **nền đen tuyệt đối**, chủ thể ở giữa, không chạm mép.

```
[hiệu ứng], centered, on a pure black background, nothing else in the image, no text. [STYLE]
```

```
pnpm assets:alpha themes/<id>/assets/raw/halo.jpg themes/<id>/assets/fx/halo.png --max 1024
```

Độ sáng thành độ trong: khói, ánh sáng giữ độ mờ tự nhiên khi đặt lên cảnh. Dùng trong bước hành động bằng `"image": "assets/fx/halo.png"`.

## 4. Đạo cụ, biểu tượng

Gen trên nền xanh lá, mỗi ảnh một vật (hoặc một hàng vật cách xa nhau), cắt bằng `pnpm assets:cut ... --auto`. Biểu tượng mức quà nên đơn giản, nhìn rõ ở cỡ 40px.

## 5. Âm thanh

- **Tiếng hiệu ứng** (`assets/sfx/<tên>.mp3`): dùng **file thu thật**, ngắn 0.5–5 giây, cuối nhỏ dần. Nguồn miễn phí bản quyền: Freesound (lọc CC0), Pixabay Sound Effects. Tiếng tổng hợp bằng code thường nghe giả và dồn dập.
- **Nhạc nền** (`assets/music/*.mp3`): không lời, đủ dài (vài phút trở lên, bài quá ngắn sẽ lặp nhiều), có quyền dùng.
- Chỉnh âm lượng các file cho đều nhau; `theme.json` → `sounds` đặt thời gian nghỉ cho từng tiếng để live đông không ồn.
- Ghi nguồn mọi asset vào `CREDITS.md` của theme.

## 6. Chữ và giao diện

- Khán giả xem trên điện thoại: khung 1080px chỉ còn khoảng 1/3. **Chữ từ 20px trở lên**, ít chữ, câu ngắn.
- Đặt bảng trong **vùng an toàn** (`/overlay?safe`): trên cùng 240px, hai bên 100px, nửa trái dưới (khung bình luận) là vùng bị che hoặc cắt.
- Bảng nền mờ, nhìn xuyên được cảnh; không che vật chính.
- Font có tiếng Việt từ Google Fonts (Be Vietnam Pro, Lora, Playfair Display…).

## Thứ tự gợi ý

1. Ảnh nền → đo `scene.json`.
2. Một tờ nhân vật → cắt → khai báo.
3. Hiệu ứng cho các mức quà.
4. Âm thanh, nhạc.
5. Giao diện: chỉnh màu, chữ trong `hud` hoặc viết giao diện riêng trong `theme.js`.
