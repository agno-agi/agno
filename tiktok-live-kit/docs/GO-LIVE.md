# Going live

**English** | [Tiếng Việt](GO-LIVE.vi.md)

The technical part of putting a theme on a TikTok LIVE. Account requirements and TikTok's content rules: see TikTok / LIVE Studio.

```
TikTok LIVE ──(gifts, likes, chat)──> TikFinity Desktop ──ws://127.0.0.1:21213──┐
            └──(fallback) direct connection ─────────────────────────────────────┤
                                                                                  ▼
                                                            Kit (run.bat, port 3939)
                                                                                  │
                        LIVE Studio / OBS <── overlay http://localhost:3939/overlay
```

## 0. Pick a setup

Answer two questions first: **which app will put the picture on air**, and **what does the account allow** (LIVE Studio access, or a stream key from TikTok)?

| Setup | Needs | Each live | Notes |
|---|---|---|---|
| **A. LIVE Studio, window capture** | LIVE Studio access | `run.bat` + `overlay.bat` | Simplest; Studio captures the overlay's Chrome window |
| **B. OBS → Virtual Camera → LIVE Studio** | LIVE Studio access, OBS | `run.bat` + OBS | **Smoothest**: OBS renders the overlay itself, the source is saved in the scene, no `overlay.bat` |
| **C. OBS with a stream key** | A stream key for the account, OBS | `run.bat` + OBS | Streams straight from OBS, no Studio |

If LIVE Studio says the account has no access, the account isn't eligible to stream from a computer yet: sort that out on TikTok first. Whatever the setup, `run.bat` must run during the whole live: it serves the overlay, the voice and the live data.

## 1. Requirements

| Software | Notes |
|---|---|
| Node.js 20+ | https://nodejs.org (`run.bat` tells you if it's missing) |
| Chrome | Setup A: opens the overlay window for LIVE Studio to capture (Studio lists Chrome windows) |
| TikTok LIVE Studio or OBS | Streaming app |
| TikFinity **Desktop** (recommended) | The installed app (the web version does not expose port 21213). Without it, use the direct connection |

## 2. Run the kit

1. Run `run.bat` (installs dependencies the first time). The black window is the server: **keep it open for the whole live**.
2. The control panel opens at http://localhost:3939: pick a theme, check connection status, test effects, toggle the demo. Its **Guide** tab (*Hướng dẫn*) sums up this page.

## 3. Put the overlay into the streaming app

**A. TikTok LIVE Studio (window capture)**
1. Run `overlay.bat`: opens the overlay as its own vertical Chrome window that **plays sound on its own** and **doesn't freeze when covered by other windows**.
2. Studio: vertical layout → **Add source → Window capture → chrome.exe** (the title is the theme name).
3. Select the source → set it to **fill** (not stretch) to cover the frame. The live frame is taller than 9:16, so about 100px is cropped on each side: keep text and panels inside the safe zone (`/overlay?safe`).
4. Don't minimize the overlay window; having it behind other windows is fine.
5. Sound: enable desktop audio capture in Studio's audio settings.

**B and C. OBS** (set up once, OBS remembers it)
1. Settings → Video: base and output resolution 1080 × 1920, 30 FPS.
2. Sources → **Browser**: URL `http://localhost:3939/overlay`, width 1080, height 1920, tick *Control audio via OBS*. Right-click → Interact, click the overlay once to enable sound.
3. **B, into LIVE Studio**: OBS → *Start Virtual Camera*. The virtual camera carries picture only, so set the browser source's sound to play out loud: Edit → Advanced Audio Properties → Audio Monitoring → **Monitor and Output**. In Studio: vertical layout → **Add source → Camera → OBS Virtual Camera**, fill the frame, and enable desktop audio capture.
4. **C, with a stream key**: Settings → Stream → Custom, paste the server URL and stream key from TikTok → *Start Streaming*. Sound goes through OBS directly.

Next time: run `run.bat`, open OBS (start the virtual camera for B). If the overlay is blank, right-click the source → Refresh.

To put the characters over your own camera or video: turn on **Green screen** (*Nền xanh để ghép trong OBS*) in the control panel's theme settings, then add a **Chroma Key** filter to the Browser source.

Stream at 30 FPS: the overlay already caps its frame rate (`scene.json` `"fps": 30`), leaving the CPU to the streaming app's encoder.

## 4. Connect live data (gifts, likes, chat)

The control panel is in Vietnamese; button names are given in brackets.

**Via TikFinity Desktop**: open TikFinity, sign in, enter the channel's exact @handle in the username box (without @), wait for TikFinity to say it's connected to the live. Control panel: choose **TikFinity Desktop** → **Connect** (*Kết nối*).

**Direct**: in the control panel choose **Direct** (*Trực tiếp*), type the channel name → **Connect** (after the channel is live).

**Auto** (*Tự động*): uses TikFinity if it's there, otherwise connects directly. On disconnect it retries (backing off up to 30 seconds).

A green status dot and a ticking "last event … ago" line mean data is flowing.

## 5. Before going on air

- In the **Test** tab (*Thử nghiệm*): try the effects and the gift buttons, use **Test voice** (*Đọc thử*), drop a 60 or 400-person crowd to check the machine copes.
- Auto mode (*Tự chạy*) shows a crowded scene; **turn it off** (*Tắt*) and click **New session** (*Phiên mới*, **Stats** tab) before the real live (connecting to a real live also stops the demo).
- Open `/overlay?safe` to check text and panels are inside the safe zone.
- Fixed lines (draws, periodic chants, prompts) are pre-rendered a few minutes after the server starts: start the kit well before the live.

## Common problems

| Symptom | What to do |
|---|---|
| Studio's window capture is black, "video signal lost" | Open the overlay with `overlay.bat` (Chrome), pick the right chrome.exe; reload the source in Studio |
| The overlay window isn't in Studio's list | Studio doesn't list Edge app windows: use Chrome (`overlay.bat` prefers Chrome) |
| Overlay is silent | The `overlay.bat` window plays sound on its own; in a normal browser tab click once. Enable desktop audio in Studio |
| Overlay is empty, no scene | Usually opened while the server was restarting; the page reloads itself after 12 seconds, or press F5 |
| "TikFinity not found at ws://127.0.0.1:21213" | TikFinity Desktop isn't open / not connected to the live, or you're using the web version. Or switch to Direct |
| Direct connection can't get the Room ID | The channel isn't live yet, or the channel name is wrong |
| TikFinity says `user_not_found` | Enter the @handle, not the display name |
| Voice is slow or patchy | Microsoft's TTS service is flaky: fixed lines are pre-rendered; set `"voice": { "fallback": "local" }` in the theme to use Windows' built-in Vietnamese voice when it fails outright |
| Text and panels cropped on phones | Keep them in the safe zone (`?safe`), at least 100px from the edges |
| Closed the black window by mistake | Run `run.bat` again, click Connect again, re-select the source in Studio if the picture is gone (OBS: refresh the browser source) |
| B: Studio shows the picture but no sound | The virtual camera has no sound: set the OBS browser source to *Monitor and Output* and enable desktop audio in Studio |
| B: "OBS Virtual Camera" isn't in Studio's camera list | Start the virtual camera in OBS before opening Studio, or restart Studio |
