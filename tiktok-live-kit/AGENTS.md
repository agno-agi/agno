# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, Gemini CLI, Cursor…) working in this repo. `CLAUDE.md` and `GEMINI.md` point here. Reply to the user in their language; the docs exist in English (`*.md`) and Vietnamese (`*.vi.md`).

## What this repo is

TikTok Live Kit: a Node server that receives TikTok LIVE events (gifts, likes, chat, joins) and a 1080 × 1920 overlay that reacts through a **theme**. Users usually ask an agent to **make a new theme** or **tweak a theme**; changing the core is rarely needed.

| Path | Contents |
|---|---|
| `src/server.js` | HTTP + WebSocket, theme loading, voice, automatic content |
| `src/core/` | Event pipeline: normalize → streaks (combos) → rules → engine → session; `voice.js`, `tts.js`, `draws.js` |
| `src/providers/` | Sources: TikFinity, direct connection, demo, manager (reconnect) |
| `public/control/` | Control panel (`/`, Vietnamese UI) |
| `public/sdk/` | Overlay SDK: `kit.js` (runs JSON actions), `scene.js` (2D crowd, camera), `scene3d.js` (same API in Three.js, `"renderer": "3d"`), `stage3d.js` (3D moving lights, lasers, video screens, `fx3d` effects), `fx.js`, `audio.js`, `hud.js`, `assets.js`, `geometry.js`, `live-sdk.js` |
| `themes/template/`, `themes/template-3d/` | Blank 2D / 3D templates to copy for a new theme |
| `tools/` | Asset processing: character sheet cutter, black → transparent |
| `docs/` | `IDEA.md` (theme idea questionnaire), `THEME.md` (full reference), `ASSETS-GUIDE.md` (making assets), `GO-LIVE.md` (going live) |
| `test/` | `node --test` |

## Commands

```bash
pnpm install          # first time (or run.bat on Windows)
pnpm start            # server at http://localhost:3939
pnpm dev              # restarts on src/ changes
pnpm test             # core tests
pnpm assets:cut  <sheet.png> <out.png> --auto --scale 0.7 --preview <check.png>   # cut a green-screen character sheet
pnpm assets:alpha <in.jpg> <out.png> --max 1024                                   # effect on black → transparent
```

`assets:*` need [uv](https://docs.astral.sh/uv/) (fetches pillow, numpy).

## Making a theme

The kit ships no ready-made theme; `themes/template` is only a blank skeleton. When the user asks for a new theme (or just "help me start"):

0. **Interview first, code later.** Walk through `docs/IDEA.md` (`docs/IDEA.vi.md` in Vietnamese) a few questions at a time: space and mood, who viewers become, what each gift level does, chat commands and draws, titles and goals, voice lines, assets they have, how they go live. Offer 2–3 concrete options when they're unsure. Then write the one-page plan from the end of `IDEA.md` and **wait for their OK** before creating files. If they already filled `IDEA.md`, read it and only ask what's missing.
1. Copy `themes/template` (2D: background image + character sheets) or `themes/template-3d` (3D: GLB models, see "3D scenes" in `docs/THEME.md`) → `themes/<theme-name>` (English, kebab-case). Set `"theme": "<theme-name>"` in `config.json` or pick it in the control panel.
2. **Assets** (from the interview): if they have none, point them to `docs/ASSETS-GUIDE.md` and write prompts from its templates. Don't draw assets in code as a substitute for real images unless the user wants that.
3. Background → `scene.json`: open `/overlay?scene`, tune `horizonY`, `person`, `floor`, `aisle`, `seats`, `points` until people stand on the floor.
4. `theme.json`: `actions` (step lists), `rules` (gift tiers, chat commands), `voice`, `characters`, `hud`, `colors`, `sounds`; optional `draws`, `periodic`, `prompts`, `reactions`, `titles`, `goals`. Every key is in `docs/THEME.md`.
5. Only write `theme.js` when JSON can't do it (custom action via `Kit.action`, custom HUD replacing `Kit.hud`).
6. Check: in the control panel's **Thử nghiệm** tab click every effect button and the gift buttons, drop a 60 / 400-person crowd, test the voice (*Đọc thử*); open `/overlay?safe` to check text is inside the safe zone.

A theme can live in its own repo: `KIT_THEMES_DIR`, `KIT_DATA_DIR`, `KIT_CONFIG` (see README).

## Going live

When the user wants to go live or set up streaming, **ask before giving steps**:

1. Which app puts the picture on air: LIVE Studio capturing the overlay window (A), OBS → Virtual Camera → LIVE Studio (B, smoothest), or OBS with a stream key (C)?
2. What the account allows: can it already use LIVE Studio, or does it have a stream key? If Studio says no access, they must sort that out on TikTok first.
3. Live data: TikFinity Desktop or the direct connection?

Then walk them through only that route in `docs/GO-LIVE.md` (`docs/GO-LIVE.vi.md` in Vietnamese). `run.bat` must run for the whole live in every route.

## Rules

- **Themes don't modify the core.** Missing features go in `theme.js`; only change `src/` or `public/sdk/` when the user wants to upgrade the kit for every theme, and run `pnpm test` afterwards.
- **1080 × 1920 frame, watched on phones**: text 20px or more; keep text and panels inside the safe zone (`Kit.safe`: top 240px, 100px each side, left half from y 1250, bottom from y 1760). Don't cover the background's main subject.
- **Viewer data is untrusted**: names and comments go into the DOM via `textContent` or escaping, never raw `innerHTML`.
- **Busy lives**: no unbounded loops, particles or sounds; use the built-in limits (`maxTags`, `fps`, `sounds.cooldown`).
- **The page can reload at any time**: state worth keeping comes from the server (`Live.on('state')`), not only page variables.
- **Voice is Vietnamese only** (`vi-VN` voices); voice lines in `theme.json` should be Vietnamese.
- **Don't commit** `data/` (live sessions, edited rules, voice cache), `assets/raw/`, keys or tokens (`signApiKey`).
- Credit assets in `themes/<id>/CREDITS.md`.
