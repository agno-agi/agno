# TikTok Live Kit

**English** | [Tiếng Việt](README.vi.md)

A shared framework for building **interactive games / overlays for TikTok LIVE**. When viewers join, comment, tap likes or send gifts, characters and effects on screen react.

The core is written once. Each topic (café, dance floor, fishing pond…) is a **theme** dropped into `themes/` and switched live from the control panel.

The kit ships no ready-made themes, only the blank `themes/template` (2D) and `themes/template-3d` (3D, Three.js) to copy for your own topic. A theme's look comes from the assets you prepare (background, characters, GIFs, video, music).

| Doc | Contents |
|---|---|
| [docs/IDEA.md](docs/IDEA.md) | Your theme idea: the questions to answer before building (space, viewers, gifts, chat, voice, assets) |
| [docs/THEME.md](docs/THEME.md) | Building a theme: structure, `scene.json`, `theme.json`, actions, voice, `theme.js` |
| [docs/ASSETS-GUIDE.md](docs/ASSETS-GUIDE.md) | Where the beauty comes from: background, character sheet, effects, sound with AI image tools, processing tools |
| [docs/GO-LIVE.md](docs/GO-LIVE.md) | Going live: LIVE Studio / OBS, TikFinity, pre-stream checks, common problems |
| [AGENTS.md](AGENTS.md) | For AI coding agents (Claude Code, Codex, Gemini…): repo map, commands, rules |
| [CHANGELOG.md](CHANGELOG.md) | Changes |

## Make your theme

1. **Idea first.** Read [docs/IDEA.md](docs/IDEA.md): what the space is, who viewers become, what each gift does, chat commands, voice lines, which assets you have. You can leave it blank and let the AI ask.
2. **Build it with AI.** Open the kit folder in Claude Code / Codex / Cursor and say: *"Read AGENTS.md and interview me with docs/IDEA.md to make a new theme."* The agent asks a few questions at a time, sums your answers up as a one-page plan, and only starts once you agree.
3. **Try it.** Pick the new theme in the control panel, use the **Test** tab (*Thử nghiệm*), then go live ([docs/GO-LIVE.md](docs/GO-LIVE.md)).

While the kit runs the blank template, the control panel shows these steps with the prompt ready to copy.

### Keeping a theme in its own repo

Each live channel can be a separate repo holding only its theme and data, running the kit's server with three environment variables:

| Variable | Meaning |
|---|---|
| `KIT_THEMES_DIR` | Folder with your themes (takes precedence over the kit's `themes/`) |
| `KIT_DATA_DIR` | Where edited rules, live sessions and voice files are stored (default: the kit's `data/`) |
| `KIT_CONFIG` | Config file overriding the kit's `config.json` (e.g. `{"theme": "my-theme"}`) |

```bat
set KIT_THEMES_DIR=%~dp0themes
set KIT_DATA_DIR=%~dp0data
set KIT_CONFIG=%~dp0config.json
node ..\tiktok-live-kit\src\server.js
```

## Live setup

```
TikTok LIVE ──> TikFinity Desktop ──ws://127.0.0.1:21213──┐
          └──> (fallback) direct connection ───────────────┤
                                                           ▼
                                    Core (Node, port 3939)
                                    dedupe · combos · gift rules · leaderboard · titles · goals
                                                           │ WebSocket
                         ┌─────────────────────────────────┴───────────────┐
                Control panel (/)                                  Theme overlay (/overlay)
                                                                          │
                              LIVE Studio (window capture of overlay.bat) or OBS (Browser source)
```

## Run

Requires Node.js 20 or newer.

- Windows: double-click **`run.bat`** (installs dependencies, starts the server and opens the control panel).
- Or:
  ```bash
  pnpm install
  pnpm start
  ```

Open http://localhost:3939/ for the control panel (its UI is in Vietnamese).

## Going live

In short: run `run.bat` → open TikFinity Desktop and connect your channel → click **Connect** in the control panel (source **Auto**) → run `overlay.bat` and add a **Window capture** source in LIVE Studio (or OBS: Browser source `http://localhost:3939/overlay`, 1080 × 1920). Step by step and common problems: [docs/GO-LIVE.md](docs/GO-LIVE.md).

Network drops, TikFinity restarts or the streaming app reloading the page need no action:
- The core reconnects, backing off from 2 to 30 seconds.
- The overlay reconnects and rebuilds the current crowd.
- The leaderboard is saved to disk, so restarting the server keeps it.

## Control panel

Five tabs, with the overlay preview and the top 3 gifters always on the right:

- **Live**: pick a source, connect, see status and "last event N seconds ago" to know data is flowing; theme settings; event log.
- **Rules** (*Luật*), edited on the web, no code:
  - Who enters the scene: everyone, or only people who chat a keyword / send a gift.
  - Gift tiers by single-gift price.
  - Per-gift overrides by ID or name, with a **gift library** (image, name, price) that learns gifts seen on live: click one to add a rule.
  - Chat commands with cooldowns.
  - A ▶ button on every row previews that row's effect before saving.
- **Test** (*Thử nghiệm*): fake viewers, crowd bursts (10 / 30 / 60 / 400 people, to check the machine copes), auto mode (normal / busy / packed), gift buttons grouped by price (small / medium / large), a button per theme effect, voice test. Fake events go through the same pipeline as a real live.
- **Stats** (*Thống kê*): session totals, leaderboard with titles, **CSV** download to thank supporters, goals, **New session** button.
- **Guide** (*Hướng dẫn*): going live in 4 steps, the three streaming setups, useful overlay URLs, common problems.

The theme can be switched while running; the overlay reloads itself.

## Making a theme

See [docs/THEME.md](docs/THEME.md). Summary: copy `themes/template`, put assets in `assets/`, measure the scene in `scene.json`, then declare the action for each gift tier in `theme.json`. Write `theme.js` for custom effects. A theme can be 2D (background image + character sheets) or 3D (`"renderer": "3d"`: GLB models, a real camera, lights; see "3D scenes" in THEME.md), or draw with anything (DOM, Canvas). External games such as Unity can also connect to the `/ws` WebSocket with `{"type":"hello","role":"overlay"}`.

## Structure

```
src/
  server.js            HTTP + WebSocket, control/overlay roles, theme loading
  core/
    normalize.js       raw data from every source → one common event shape
    streaks.js         gift combos (counts only the increase, no double counting)
    rules.js           rules: gift ID → gift name → price tier; chat commands; join keywords
    engine.js          pipeline: dedupe → combos → rules → session → broadcast
    session.js         players, leaderboard, titles, goals, persistence, CSV export
    gift-catalog.js    remembers gifts seen
    voice.js, tts.js   voice line templates (comment filtering, cooldowns), Vietnamese TTS, pre-rendered fixed lines
    draws.js           chat draws (fortune sticks, card draws...)
  providers/           tikfinity · connector (direct) · demo · manager (reconnect, source switching, silence watch)
public/
  control/             control panel
  sdk/                 live-sdk (connection) · geometry · assets · fx · audio · scene (crowd, camera) · hud · kit (runs JSON actions)
themes/<id>/           theme.json + scene.json + index.html + theme.js + assets/
data/                  (not in git) settings, edited rules, live sessions, gift list
tools/                 asset processing: cut-sheet.py (pnpm assets:cut), black-to-alpha.py (pnpm assets:alpha)
test/                  pnpm test
run.bat, overlay.bat   start the server; open the overlay as a Chrome window for LIVE Studio to capture
```

## Configuration

`config.json` holds the defaults. Anything changed in the control panel (channel, source, theme) is saved separately in `data/settings.json`.

| Key | Meaning |
|---|---|
| `port`, `host` | Default `127.0.0.1:3939`, this machine only. `host` accepts a list (`"127.0.0.1,192.168.137.1"`) to open exactly one more address (e.g. the PC's Wi-Fi hotspot) |
| `allowLan` | `true` lets other machines on the LAN connect (e.g. controlling from a phone) |
| `provider` | `auto` \| `tikfinity` \| `connector` |
| `tikfinityUrl` | Default `ws://127.0.0.1:21213/` |
| `autoConnect` | Connect automatically when the server starts |
| `signApiKey` | Euler Stream key if the direct source gets rate-limited |
| `maxJoinsPerSecond` | Caps join floods on busy lives (default 15/s) |
| `playerTtlMinutes` | How long a silent viewer stays before leaving the scene |
| `watchdogSeconds` | Reconnect the direct source after this long without events |

## Notes

- The direct source (`tiktok-live-connector`) is an unofficial library. If TikTok changes its protocol, run `pnpm update tiktok-live-connector`. Prefer TikFinity as the main source.
- On busy lives TikTok does not send every join and every like. Gifts and comments are nearly complete.
- Voice and template text are Vietnamese: TTS uses the two `vi-VN` voices (`VOICES` in `src/core/tts.js`). Voice lines live in `theme.json`.

## License

[MIT](LICENSE). The kit is an independent project, not affiliated with or endorsed by TikTok. Assets you put in a theme (images, music, fonts) follow their own licenses.
