# Making a theme

**English** | [Tiếng Việt](THEME.vi.md)

A theme is a folder: images and sounds in `assets/`, scene layout in `scene.json`, content and rules in `theme.json`, custom parts (if needed) in `theme.js`. The core handles the live connection, dedupe, gift combos, gift rules, leaderboard, titles, goals and voice. Most themes **need no code**: just JSON.

```
themes/<theme-name>/
  index.html     loads the SDK (copy from themes/template, no edits needed)
  theme.json     actions, gift rules, chat commands, titles, goals, voice, characters, HUD
  scene.json     background, perspective, floor, aisle, seats, anchor points, ambient effects
  theme.js       (optional) custom actions / HUD
  assets/        background.jpg, characters, effects, music/*.mp3, sfx/<name>.mp3
```

## Quick start

1. Copy `themes/template` to `themes/<new-name>` (English, kebab-case). To keep the theme in its own repo, see "Keeping a theme in its own repo" in the README.
2. Put the background in `assets/`, open the overlay with `?scene` to see the measuring grid, then tune `scene.json` until people stand on the floor at the right size.
3. Edit `theme.json`: actions per gift tier, chat commands, voice.
4. Open the control panel, pick the theme; in the **Test** tab (*Thử nghiệm*) click the effect buttons and drop a crowd to see a busy scene.

Folders starting with `_` or `.` are ignored (use them for drafts).

## Checking the overlay

| URL | Purpose |
|---|---|
| `/overlay` | The page for OBS / LIVE Studio (1080 × 1920) |
| `/overlay?mute` | Muted (preview inside the control panel) |
| `/overlay?scene` | Draws the measuring grid: horizon, floor, aisle, obstacles, seats, anchor points |
| `/overlay?safe` | Shades in red the areas covered by TikTok's UI or cropped on tall phones (`Kit.safe`) |

Safe zones on the 1080 × 1920 frame: top 240px (channel name, viewers), 100px on each side (cropped on tall screens), the left half from y 1250 down (comments box), the bottom from y 1760 (input box, gift button). On a phone, text shrinks to about 1/3: keep readable text at 20px or more.

## scene.json

```jsonc
{
  "background": "assets/background.jpg",       // image / video (mp4, webm) / gif
  "horizonY": 700,                             // horizon: people get smaller the closer they are to it
  "person": {
    "refY": 1000, "refHeight": 60,             // at height refY a person is refHeight px tall
    "exponent": 0.45,                          // perspective steepness
    "idleStyle": "stand",                      // placeholder shape before character art exists: stand | kneel
    "cushion": { "width": 0.5, "depth": 0.32, "color": "#6e170f", "light": "#b8392a" }  // cushion under kneeling / seated people
  },
  "floor": { "top": 1040, "bottom": 1640, "left": 30, "right": 1050 },   // floor area for the crowd
  "aisle": { "x": 540, "half": [[1000, 34], [1900, 100]], "lane": 90 },  // center aisle (half width by depth), walking lane
  "spacing": { "col": 0.8, "row": 0.4 },       // spacing between people, in person heights
  "obstacles": [{ "x0": 0, "x1": 105, "y0": 0, "y1": 1130 }],            // pillar bases, tables... no people here
  "seats": [[440, 980], [640, 980]],           // honor seats for top gifters
  "points": { "stage": [540, 930], "focus": [540, 600], "entry": [540, 2000] },  // anchor points for actions, camera
  "emitters": [{ "preset": "smoke", "at": "stage", "every": 90 }],      // continuous effects (at: anchor, [x, y], or x / y)
  "glows": [[300, 760, 40]],                   // flickering lights [x, y, radius] (candles, lamps)
  "sunrays": { "from": 1060 },                 // soft diagonal sun rays
  "fill": { "rows": 2 },                       // always fill the first N rows with unnamed people (not counted as viewers)
  "maxTags": 8,                                // max name tags at once (besides top 3); tags never overlap
  "fps": 30                                    // frame cap, leaves CPU for the streaming app
}
```

The crowd spreads out on its own: sparse when the room is empty, denser when busy; when there is no room left, the person silent the longest leaves.

## theme.json

### Actions: lists of JSON steps

```jsonc
"actions": [
  {
    "id": "small", "label": "Small gift", "icon": "assets/icon.png", "card": "1 coin",
    "steps": [
      { "walk": "stage" },                                   // walk to an anchor / "home" back to own spot
      { "pose": "stand" },
      { "play": "bow", "times": 3, "each": [{ "sound": "bell" }] },   // play an animation n times ("count" = gift count)
      { "fx": "emit", "preset": "spark", "at": "head", "count": 12 },
      { "fx": "halo", "at": "focus", "image": "assets/fx/halo.png" },
      { "fx": "text", "at": "head", "text": "+{total}" },
      { "camera": "person", "zoom": 1.6 }, { "spotlight": true }, { "aura": 1 }, { "boost": 1.3 },
      { "say": "Thanks {ten}!" }, { "toast": "{ten} just sent {qua}" },
      { "crowd": [{ "play": "bow" }] },                      // the whole crowd does it
      { "js": "myAction" }                                   // calls Kit.action('myAction', fn) in theme.js
    ]
  }
]
```

Effects (`fx`): `emit` (smoke heart spark petal confetti snow leaf bubble firefly ember coin star), `rain`, `halo`, `rays`, `pillar`, `text`, `fly`, `sprite`, `fireworks`, `flash`, `shake`. Pass your own image with `"image"`.
Step text accepts `{ten}` (name) `{qua}` (gift) `{count}` `{total}` `{label}`.

### Rules

```jsonc
"rules": {
  "joinMode": "all",                         // "all": anyone who interacts enters; "keyword": must chat a keyword
  "joinKeywords": ["hello"],
  "bigGiftCoins": 100,                       // from this many coins "bigGift" also runs
  "giftTiers": [{ "minCoins": 1, "action": "small", "label": "Small gift" }],   // by the price of ONE gift
  "giftOverrides": [{ "giftId": "5655", "names": ["rose"], "action": "small" }],
  "chatCommands": [{ "keywords": ["draw"], "match": "contains", "action": "draw", "draw": "fortune", "label": "draw a card", "cooldownMs": 30000 }]
},
"bigGift":   { "steps": [...] },              // extra steps for big gifts
"reactions": { "like": [...], "chat": [...], "follow": [...], "share": [...], "title": [...], "goal": [...] },
"titles": [{ "minCoins": 200, "label": "Guardian", "aura": 0.45 }],  // aura: permanent glow by title (used in theme.js)
"goals":  [{ "id": "likes", "metric": "likes", "label": "Likes", "every": 1000 }]
```

Gift matching order: **gift ID** → **name / alias** (accent-insensitive) → **price tier**. Rules can be edited in the control panel and are saved to `data/rules-<id>.json`.

### Chat draws (fortune sticks, card draws, readings...)

```jsonc
"draws": { "fortune": { "perDay": true, "items": [{ "title": "Card 1 · Great luck", "text": "Everything goes your way today." }] } }
```

A chat command with `"draw": "fortune"` makes the server draw one item (one fixed item per person per day with `perDay`). The overlay receives it as `ev.draw` (the built-in HUD shows its `title` and `text` fields), and the voice uses the `voice.draw` template, where every item field is a variable (`{title}`, `{text}`…).

### Voice

```jsonc
"voice": {
  "enabled": true, "voice": "vi-VN-NamMinhNeural",            // or vi-VN-HoaiMyNeural
  "gift": ["Cảm ơn {ten} đã tặng {qua}{lan}. {loi}."], "bigGift": [...],
  "join": ["Chào {ten}!"], "chat": ["{ten} nhắn: {chat}."],   // comments are filtered for profanity, links, emoji
  "follow": [...], "title": [...], "goal": [...],
  "command:wish": ["{ten} gửi lời chúc: {loi}."],            // a line per chat command (by action id)
  "draw": ["{ten} rút được {title}. {text}"], "drawAgain": [...],
  "cooldown": { "join": 18000, "chat": 10000 },               // gap per line kind (ms)
  "delay": { "draw": 2300 },                                  // wait so the voice matches when the visual appears
  "fallbackWords": ["Chúc gia đình bình an"],                // {loi} when the person hasn't chatted yet
  "fallback": "local"                                         // (optional) if the service fails, use Windows' built-in Vietnamese voice
}
```

Variables: `{ten}` name, `{qua}` gift, `{lan}` ", N times", `{xu}` coins, `{hanh_dong}` action label, `{danh_hieu}` title, `{muc_tieu}` goal, `{gia_tri}` goal value, `{loi}` the person's last words, `{chat}` the comment.

The voice uses Microsoft's free TTS service (needs internet, sometimes slow); only the two Vietnamese voices are supported. Gift, draw and title lines go first; greetings and comment read-outs only play when the queue is free. Fixed lines (draws, periodic chants, prompts) are **pre-rendered and cached in `data/tts-cache`**: next time they play instantly.

### Automatic content

```jsonc
"periodic": { "everyMinutes": 3, "quietSeconds": 0, "title": "ANNOUNCEMENT", "items": ["..."] },  // quietSeconds > 0: only when quiet
"prompts":  { "everySeconds": 90, "quietSeconds": 25, "items": ["Type draw to get your card."] }  // interaction prompts when chat is quiet
```

### Characters

```jsonc
"characters": [{
  "id": "guest", "label": "Guest", "keywords": ["guest"],          // chat a keyword to switch look
  "sheet": "assets/chars/guest.png", "frames": 32,                 // horizontal strip of equal frames, auto-trimmed by transparency
  "walkUp": [0, 1, 2], "walkDown": [8, 9], "walkSide": [12, 13],   // directional walk frames (side walk drawn facing right)
  "poses": { "idle": 16, "stand": 24, "cheer": 26 }
}],
"animations": { "bow": { "frames": ["idle", "idle@0.8", "idle"], "ms": 1300 } },   // "idle@0.8": squashed lower (bow)
"npcs": [{ "id": "host", "character": "guest", "at": [480, 870], "showName": false, "cushion": false, "reactions": { "bigGift": [...] } }]
```

AI-drawn character sheets are rarely evenly spaced: use the sheet cutter (detects each pose, removes the green background) `pnpm assets:cut ... --auto`, full workflow in [ASSETS-GUIDE.md](ASSETS-GUIDE.md).

### Built-in HUD, colors, sounds

```jsonc
"hud": { "title": { "text": "Channel name" }, "counters": true, "giftCard": { "verb": "sent", "unit": "coins" }, "tiers": true,
         "board": { "title": "TOP FANS", "size": 3 }, "ticker": { "title": "Just sent" }, "goal": true, "guide": { "title": "How to play" } },
"colors": { "accent": "#ffd987", "panel": "...", "border": "...", "glow": "..." },
"sounds": { "bell": { "cooldown": 3000, "duck": 0.7 }, "like": false }   // assets/sfx/<name>.mp3, music: assets/music/*.mp3
```

## 3D scenes (Three.js)

A theme can use a 3D scene instead of a background image: GLB / glTF models for the place and the characters, a real camera that flies to the gifter, lights and glow. Everything else stays the same: `theme.json` actions, rules, voice, HUD, effects (drawn on a 2D layer on top), name tags and chat bubbles.

Start from `themes/template-3d` (its `index.html` adds the Three.js import map and `/sdk/scene3d.js`). Without models it shows placeholder people (body + head) that still bow, bounce and walk, so you can test the flow first.

```jsonc
// scene.json, units are metres: x across, y up, z towards the camera (the stage is at negative z)
{
  "renderer": "3d",
  "camera": { "position": [0, 7.5, 19], "target": [0, 1.2, 0], "fov": 55 },
  "world": "assets/3d/stage.glb", "worldScale": 1,      // the place (optional; without it a flat floor is drawn)
  "background": "#17141f", "fog": { "color": "#17141f", "near": 22, "far": 48 },
  "lights": { "ambient": 0.9, "sun": { "intensity": 1.6, "position": [6, 12, 8], "shadows": false },
              "points": [{ "at": [0, 3, -4], "color": "#ff8a5c", "intensity": 25, "distance": 12 }] },
  "floor": { "x": [-4, 4], "z": [-0.5, 8] },            // where the crowd stands
  "aisle": { "x": 0, "half": 0.6 }, "spacing": 0.8, "fill": { "rows": 0 },
  "seats": [[-1.4, -1.8], [1.4, -1.8]],                 // honour seats for top gifters
  "points": { "stage": [0, -3.2], "focus": [0, 2, -4], "entry": [0, 14] },   // [x, z] on the floor or [x, y, z]
  "bloom": { "strength": 0.5, "radius": 0.4, "threshold": 0.85 },
  "facing": "focus",                                    // idle people look at "focus" / "stage"; "camera" = face the viewers
  "maxAnimated": 120, "fps": 30
}
```

```jsonc
// theme.json: a 3D character is a rigged GLB with its animation clips inside
"characters": [{
  "id": "guest", "label": "Guest", "keywords": ["guest"],
  "model": "assets/3d/guest.glb", "height": 1.7,        // scaled to this height in metres
  "clips": { "idle": "Idle", "walk": "Walk", "cheer": "Wave", "nod": "Interact", "dance": "Dance" }
}],
"animations": { "bow": { "clip": "Bow", "ms": 1600 } }  // optional: how long one "play" lasts
```

`pose` and `play` steps use the names in `clips`; a missing name falls back to a clip with the same name (case-insensitive), then to `idle`. `walk` is used while moving. The same step lists work in 2D and 3D: `walk`, `play`, `camera`, `spotlight`, `aura`, `boost`, `say`, `crowd`, `fx`.

Models: CC0 packs such as Quaternius, Kenney, KayKit, or Mixamo animations. Prefer characters under ~5k triangles with 1–2 materials; tested on a Radeon 780M laptop GPU, about 110 Quaternius characters (around 10 parts each, ~1,150 draw calls) render in 20–23 ms, enough for 30 fps. Far-away people update their animation less often (`maxAnimated`). `?scene` draws the floor, slots, seats and points projected from the 3D world.

In `theme.js`, `Kit.scene.three` gives `{ THREE, scene, camera, renderer }` to add your own 3D objects.

### Stage kit: moving lights, lasers, video screen

```jsonc
// scene.json
"stage": {
  "lights": [{ "at": [-4, 6.5, -3], "color": "#ff3cac", "target": [-1.5, 2], "sweep": 2.5, "speed": 0.55, "angle": 14, "intensity": 40, "beam": 0.28 }],
  "lasers": { "from": [0, 5.5, -4.5], "count": 8, "colors": ["#00ffd5", "#ff2bd6"], "spread": 70, "speed": 0.5, "width": 0.035, "always": false },
  "screens": [{ "at": [0, 4.2, -5.5], "size": [5.6, 3.15], "folder": "video" }]   // or "video": "assets/x.mp4", "videos": [...], "image": "..."
}
```

- **Moving lights**: a real spotlight on the floor plus a visible beam, sweeping around `target`. They pulse with the music when `Kit.fx.beat.bpm` is set.
- **Lasers**: a fan of thin beams, shown during `party` (or always with `"always": true`).
- **Screens**: muted video in a loop; `"folder": "video"` plays every `.mp4` / `.webm` dropped into `assets/video/`, one after another (like a DJ screen).

Steps for actions (2D themes ignore `stage` and turn `fx3d` into the closest 2D effect, so one theme.json works in both):

| Step | Effect |
|---|---|
| `{ "stage": "party", "duration": 7000 }` | lights brighter and faster, lasers on |
| `{ "stage": "calm" }` / `{ "stage": "strobe", "duration": 1200 }` | back to normal / lights flash |
| `{ "fx3d": "fireworks", "at": "stage", "bursts": 5 }` | 3D firework bursts above a point |
| `{ "fx3d": "confetti", "count": 300 }` | confetti falling over the whole crowd |
| `{ "fx3d": "beam", "at": "person", "color": "#ffd27a" }` | light column on the gifter |
| `{ "fx3d": "ring", "at": "person" }` | glowing ring spreading on the floor |

### Green screen for OBS

Turn on **Green screen** (*Nền xanh để ghép trong OBS*) in the control panel's theme settings, or open the overlay with `?chroma`. The background becomes pure `#00ff00` (`scene.json` `"chroma"` to change it); in 3D the floor, world model, fog, glow, beams, lasers and screens are hidden so only people, tags and effects remain. In OBS add a **Chroma Key** filter to the Browser source. Works for 2D themes too.

## theme.js: custom parts

```js
Kit.action('lantern', (person, ev) => { /* step { "js": "lantern" } */ });
Kit.on('frame', (t, dt) => { /* every frame */ });
Kit.on('speak', (e) => {}); Kit.on('speakEnd', (e) => {});   // voice line starts / ends (e.about: gift, draw, chat...)
Kit.hud = { init, giftCard, ticker, state, guide, toast, periodic, draw, remember, reset };  // replace the whole HUD
```

API: `Kit.scene` (people, anchor points, camera), `Kit.fx` (effects), `Kit.audio` (`sfx('bell')`), `Kit.safe` (safe zones), `Live.on(...)` (raw events: join, chat, like, gift, command, follow, share, title, goal, periodic, prompt, tts, state, reset).

## Keeping a theme stable on live

- **Stay bounded**: a busy live can send dozens of events per second; the kit already caps people, tags and sounds at once, don't add unbounded loops.
- **Don't trust viewer data**: names and comments put into HTML must go through `textContent` or an escape function.
- **The page can reload at any time** (OBS, network drop): the kit rebuilds the current people; if stuck on an empty screen for 12 seconds it reloads itself.
- **Have a real person on stream**: a live with only a self-running game is easily flagged by TikTok as "unoriginal content". A host camera and talking helps.
