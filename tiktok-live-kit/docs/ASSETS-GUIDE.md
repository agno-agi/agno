# Where the beauty comes from

**English** | [Tiếng Việt](ASSETS-GUIDE.vi.md)

The kit handles motion, effects, voice and game rules. **The beauty comes from assets**: background, characters, effects, sound. The kit ships no assets; this guide shows how to prepare your own, mostly with AI image tools (GPT Image, Gemini / Flow, Midjourney…).

```
Layer 4  UI: panels, cards, text                 ← CSS in theme.js or the built-in hud
Layer 3  Effects: halo, smoke, rays, particles   ← black background → transparent
Layer 2  Characters, props                       ← green-screen animation sheet → cut into frames
Layer 1  Background                              ← most important, sets 70% of the feel
```

## General rules

- **One vibe for the whole set**: generate the background first, then give that background as a reference for every later asset (*"match the colors and lighting of this image"*). Reuse one style block (STYLE) at the end of every prompt.
- **Same rendering style**: photo background → photo / 3D characters; painted background → characters painted the same way. A mismatch looks "pasted on" immediately.
- **Separable backgrounds**: people and objects on **flat chroma green (#00FF00)**; light and smoke on **pure black**. No shadows, no floor, no text, no frames.
- Generate at the highest resolution available (2K / 4K). Keep raw images in `themes/<id>/assets/raw/` (not in git), processed ones in `assets/`.
- AI tools often add a ✦ mark in the bottom-right corner: the kit's processing tools remove it.

## 1. Background (9:16, 1080 × 1920)

Think in **bands from top to bottom** and write them into the prompt as percentages of the height, for example: 0–40% the main subject (stage, altar, counter…), 40–60% decorations and interaction points, 60–100% **empty floor** where the kit places the crowd.

- Camera about 2–3 m high, straight-on, symmetrical: perspective is easy to measure and the crowd looks natural.
- **No people** in the background (the kit adds them).
- Leave **enough empty floor** and (if needed) a center aisle for people to walk in.
- Most reliable: draw a **layout sketch** with simple blocks (main subject, rows, aisle) and give it to the AI with *"Turn this flat layout sketch into a photorealistic image, keep exactly the same composition, sizes and positions"*.

```
Vertical 9:16 [photo / painting] of [place], perfectly symmetrical, straight-on view, camera about 3 meters high.
Top 40%: [main subject], large and centered.
From 40% to 60%: [decorations, interaction points], symmetrical.
Bottom 40%: empty [floor material] floor with [aisle / carpet] down the center. No people anywhere.
[STYLE]
```

Once you have it: open `/overlay?scene` and tune `scene.json` (horizon, person size, floor, aisle, obstacles, seats, anchor points) until people stand on the floor at the right size.

## 2. Characters: one animation sheet

**One character is enough**: the kit flips it left and right per person. Generate **one 16:9 image with every move**, in a grid, one move per row, read left to right as consecutive frames like a cartoon.

List the moves **the theme actually uses**: idle (95% of the time), walking in (seen from behind), walking out (facing the camera), walking sideways, and the actions for gifts / chat commands.

```
Create ONE 16:9 animation model sheet (sprite sheet) of a single character for a 2.5D live-stream game set in the place of the attached reference image (use it only for colors and lighting).
CHARACTER: [character, outfit].
ART STYLE: [same style as the background].
LAYOUT: exactly [N] drawings of the SAME character in a strict invisible grid of [columns] columns and [rows] rows, each centered in its own cell with clear empty space around it, feet on the bottom line of the cell, all at the same scale, same camera slightly above.
BACKGROUND: perfectly flat pure chroma green (#00FF00). No floor, no cushion, no shadow. ABSOLUTELY NO text, numbers, labels or grid lines.
Row 1: walking away from the camera (seen from behind), 6-frame walk cycle with clearly alternating legs.
Row 2: walking toward the camera, same walk cycle.
Row 3: walking to the right (side view), same walk cycle.
Row 4: [idle and the frames of the main action].
Row 5: [other actions].
FINAL CHECK: same character and scale in every cell; background perfectly flat green; no text. Regenerate if any check fails.
```

Cut the sheet (detects each pose even when the AI breaks the grid, removes the green, drops stray digits, keeps relative scale between poses):

```
pnpm assets:cut themes/<id>/assets/raw/character.png themes/<id>/assets/chars/character.png --auto --scale 0.7 --preview raw/check.png
```

Open the check image (frames are numbered) and declare it in `theme.json` → `characters`: `sheet`, `frames`, `walkUp` / `walkDown` / `walkSide`, `poses`. For a missing frame use `"idle@0.8"` (squashed lower) for bows.

## 3. Effects (black background)

Halos, rays, smoke, sparkles, fireworks: generate on **pure black**, subject centered, not touching the edges.

```
[effect], centered, on a pure black background, nothing else in the image, no text. [STYLE]
```

```
pnpm assets:alpha themes/<id>/assets/raw/halo.jpg themes/<id>/assets/fx/halo.png --max 1024
```

Brightness becomes opacity: smoke and light keep their natural softness over the scene. Use it in an action step with `"image": "assets/fx/halo.png"`.

## 4. Props, icons

Generate on green, one object per image (or a row of well-spaced objects), cut with `pnpm assets:cut ... --auto`. Gift tier icons should be simple and readable at 40px.

## 5. Sound

- **Sound effects** (`assets/sfx/<name>.mp3`): use **real recordings**, 0.5–5 seconds, fading out. Royalty-free sources: Freesound (filter CC0), Pixabay Sound Effects. Sounds synthesized in code usually sound fake and harsh.
- **Background music** (`assets/music/*.mp3`): instrumental, long enough (several minutes; short tracks repeat a lot), licensed for use.
- Level the files to similar loudness; `theme.json` → `sounds` sets a cooldown per sound so busy lives don't get noisy.
- Credit every asset in the theme's `CREDITS.md`.

## 6. Text and UI

- Viewers watch on phones: the 1080px frame shows at about 1/3. **Text 20px or more**, little text, short sentences.
- Keep panels inside the **safe zone** (`/overlay?safe`): top 240px, 100px on each side, the lower left half (comments box) gets covered or cropped.
- Translucent panels that let the scene show through; don't cover the main subject.
- Fonts with Vietnamese support from Google Fonts (Be Vietnam Pro, Lora, Playfair Display…).

## Suggested order

1. Background → measure `scene.json`.
2. One character sheet → cut → declare.
3. Effects for the gift tiers.
4. Sound, music.
5. UI: colors and text in `hud`, or your own UI in `theme.js`.
