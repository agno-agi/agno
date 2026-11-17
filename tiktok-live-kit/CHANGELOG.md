# Changelog

**English** | [Tiếng Việt](CHANGELOG.vi.md)

## Unreleased

- 3D stage kit (`sdk/stage3d.js`, `scene.json` `"stage"`): moving lights with visible beams, lasers, looping video screens (a folder works like a DJ playlist); steps `{ "stage": "party" | "calm" | "strobe" }` and `{ "fx3d": "fireworks" | "confetti" | "beam" | "ring" }`, which 2D themes map to 2D effects.
- Green screen for OBS: new **Green screen** setting or `?chroma`, pure `#00ff00` background in 2D and 3D.
- Control panel crowd buttons let people in at the engine's join rate, so 150 / 400 really arrive.

- 3D scenes: `scene.json` `"renderer": "3d"` runs the scene in Three.js (`sdk/scene3d.js`) with the same API as 2D: GLB world and rigged characters with animation clips, crowd slots, aisle, honour seats, camera that flies to the gifter, lights, bloom, placeholder people when models are missing. New blank `themes/template-3d`. Three.js 0.186 served at `/vendor/three/`.

- Control panel in five tabs (Live, Rules, Test, Stats, Guide) with the overlay preview always on the right: gift library with images (click to add a rule), a preview button on every rule row, gift test buttons grouped by price, 10 / 30 / 60 / 400-person crowd bursts, built-in going-live guide.
- Theme idea questionnaire `docs/IDEA.md`: the AI agent interviews the user and gets a one-page plan approved before building; the control panel shows the steps and a ready prompt while the blank template runs.
- Control panel restyled to match duycuf.vn: dark navy panels with soft blue / orange glows, ember orange accent, Be Vietnam Pro and JetBrains Mono.
- Action icons that are image files now show as images in the control panel instead of their file path.
- Going live: pick a setup first (LIVE Studio window capture, OBS virtual camera, OBS stream key), full OBS steps.

## 1.0.1 (2026-11-02)

- Voice: greetings and comment read-outs are no longer dropped while fixed lines are pre-rendered in the background.
- Docs in English, Vietnamese versions in `*.vi.md`.

## 1.0.0 (2026-11-01)

First shared release.

- **Live sources**: TikFinity Desktop, direct connection (`tiktok-live-connector`), demo; auto source selection, auto reconnect, silence watch.
- **Core**: dedupe, gift combos, gift rules (ID → name → price tier), chat commands with cooldowns, join keywords, leaderboard, titles, goals, session persistence, CSV export.
- **Control panel**: connection, Test Lab (fake viewers, gifts, combos, auto mode), rule editing on the web, theme switching while running.
- **Overlay SDK**: perspective crowd (aisle, seats, obstacles, front rows always filled with `fill`), characters from an animation sheet (directional walks, poses, moves), effects (particles, fireworks, rays, image / GIF / video / Lottie), sounds with cooldowns, camera, built-in HUD, safe zones `?safe`, `fps` cap, auto reload when stuck.
- **JSON actions**: each gift tier / chat command is a list of steps, no code needed; `theme.js` for custom parts.
- **Vietnamese voice**: gift thanks, join greetings, comment read-outs (profanity and link filtering), per-command lines, priority for important lines, pre-rendered fixed lines, Windows voice fallback.
- **Automatic content**: chat draws (`draws`), periodic announcements (`periodic`), interaction prompts when chat is quiet (`prompts`).
- **Theme in its own repo**: `KIT_THEMES_DIR`, `KIT_DATA_DIR`, `KIT_CONFIG`.
- **Asset tools**: `pnpm assets:cut` (cuts a green-screen character sheet, auto-detects each pose), `pnpm assets:alpha` (black background → transparent, removes corner marks).
- **Docs**: `docs/THEME.md`, `docs/ASSETS-GUIDE.md`, `docs/GO-LIVE.md`, `AGENTS.md` for AI coding agents.
