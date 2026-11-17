# Put the theme's assets here

**English** | [Tiếng Việt](README.vi.md)

The blank template ships no images, music or sounds. Without assets the engine draws placeholder shapes. Whether the theme looks good depends on the assets you prepare: see the kit's `docs/ASSETS-GUIDE.md` for where to find them or how to generate them with AI.

| Where | Used for | Declared in |
|---|---|---|
| `background.jpg` (or `.png`, `.webp`) | 1080×1920 background | `scene.json` → `background` |
| `background.mp4` / `.webm` | looping video background (optional, nicer than a still) | `scene.json` → `backgroundVideo` |
| `chars/*.png` | multi-pose character sheet, transparent background | `theme.json` → `characters` |
| `chars/*.gif` / `*.webm` | ready-animated characters (dancing, walking...) | `theme.json` → `characters[].idleAnim` |
| `fx/*.png` / `*.gif` / `*.webm` / `*.json` (Lottie) | effect images | step `{ "fx": "sprite", "image": ... }` or a particle's `image` |
| `sfx/<name>.mp3` | sound effects, called by name | step `{ "sound": "<name>" }`; `sfx/like.mp3` plays on likes automatically |
| `music/*.mp3` | background music, looped as a playlist | loaded automatically |
| `ui/panel.png` | HUD panel frame | `theme.json` → `hud.panelImage` |

Record the source and license of each asset in the theme's `CREDITS.md`.
