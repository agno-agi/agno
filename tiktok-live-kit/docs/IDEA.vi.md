# Ý tưởng theme của bạn

[English](IDEA.md) | **Tiếng Việt**

Kit không kèm theme làm sẵn. Trước khi làm, trả lời các câu dưới đây: tự điền, hoặc để AI (Claude Code, Codex…) hỏi lần lượt từng câu (AI đọc [AGENTS.md](../AGENTS.md)). Trả lời ngắn là được; "chưa biết" cũng là một câu trả lời, AI sẽ gợi ý vài lựa chọn.

## 1. Không gian

- **Chủ đề**: buổi live diễn ra ở đâu? (quán cà phê, hồ câu cá, lớp học, khán đài sân bóng, khu vườn, trạm vũ trụ…)
- **Không khí**: ấm cúng, vui nhộn, sôi động, thư thái hay trang nghiêm?
- **Điểm chính** ở phần trên khung hình: sân khấu, quầy, cây lớn, màn hình…
- **Người dẫn**: bạn có lên hình không, hay cả khung hình là cảnh?

## 2. Người xem

- Ai vào live thì **thành ai** trong cảnh? (khách quán, fan, con cá, học sinh…)
- Ai được vào cảnh: **mọi người** có tương tác, hay chỉ người chat **từ khoá** / tặng quà?
- Lúc chờ họ làm gì? (ngồi, nhún nhảy, đi dạo, cổ vũ)

## 3. Quà

Mỗi mức quà thì trên màn hình xảy ra chuyện gì. Một món quà có thể kéo theo nhiều việc (đi tới đâu đó, làm một động tác, hiệu ứng, tiếng, câu đọc).

| Mức | Xu mỗi món | Chuyện gì xảy ra |
|---|---|---|
| Nhỏ | 1–9 | ví dụ: người tặng sáng lên, vẫy tay |
| Vừa | 10–99 | ví dụ: đi lên sân khấu làm một động tác |
| Lớn | 100+ | ví dụ: pháo hoa, camera zoom, cả đám đông reo hò |

Có món quà cụ thể nào cần hành động riêng không? (ví dụ: Rose = tung hoa)

## 4. Chat

- **Lệnh chat**: người xem gõ gì thì được gì? (ví dụ: "nhảy" → nhân vật nhảy, "gọi cà phê" → hiện ly cà phê)
- **Bốc thăm**: rút lá bài, lời chúc, câu nói hay mỗi ngày qua chat, miễn phí?
- Có **đọc bình luận** thành tiếng không?

## 5. Thăng hạng

- **Danh hiệu** theo tổng xu (ví dụ: Khách quen → VIP → Huyền thoại)?
- **Mục tiêu** chung cả phòng (ví dụ: mỗi 1.000 tim thì có chuyện gì đó)?
- **Bảng xếp hạng**: có ghế danh dự hay bục cho top người tặng?

## 6. Giọng đọc và nội dung tự chạy

Giọng đọc chỉ có tiếng Việt (hai giọng: nữ HoaiMy, nam NamMinh).

- Đọc gì khi có người **vào**, **tặng quà**, **lên danh hiệu**?
- **Thông báo định kỳ** (vài phút một lần) và **lời mời** khi chat vắng ("Gõ nhảy để vào sàn nào!")?

## 7. Asset

- Đã có sẵn gì: ảnh nền, nhân vật, hiệu ứng, nhạc nền, tiếng hiệu ứng?
- Thiếu thì gen bằng AI (xem [ASSETS-GUIDE.vi.md](ASSETS-GUIDE.vi.md)), hay dùng hình khối tạm trước?
- Phong cách: ảnh thật, 3D, anime, hoạt hình phẳng?
- **2D hay 3D?** 2D = một ảnh nền + tờ nhân vật (dễ làm đẹp bằng ảnh AI). 3D = mô hình GLB và camera chuyển động (có sẵn bộ mô hình CC0 miễn phí; nặng máy hơn).

## 8. Lên live

- Phát bằng cách nào: LIVE Studio quay cửa sổ, OBS → camera ảo → LIVE Studio, hay OBS bằng khoá phát? (xem [GO-LIVE.vi.md](GO-LIVE.vi.md))
- Nhận dữ liệu live qua TikFinity Desktop hay nối trực tiếp?

## AI trả lại gì

Trước khi viết code, AI tóm câu trả lời thành một bản kế hoạch một trang và chờ bạn đồng ý:

```
Theme: <tên> (thư mục themes/<ten-kebab>)
Cảnh: <ảnh nền, điểm chính, chỗ đám đông đứng>
Người xem: <thành ai, luật vào cảnh, lúc chờ làm gì>
Quà: nhỏ → <các bước> · vừa → <các bước> · lớn → <các bước> · <quà riêng>
Chat: <lệnh chat> · <bốc thăm>
Danh hiệu / mục tiêu: <danh sách>
Giọng đọc: <câu khi vào / tặng quà / lên danh hiệu> · định kỳ: <…> · lời mời: <…>
Asset: đã có <…> · cần thêm <…> (kèm prompt theo kiểu ASSETS-GUIDE)
Lên live: <cách A / B / C>, <TikFinity / trực tiếp>
```
