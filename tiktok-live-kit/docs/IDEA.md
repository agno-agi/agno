# Your theme idea

**English** | [Tiếng Việt](IDEA.vi.md)

The kit ships no ready-made theme. Before building one, answer the questions below: fill them in yourself, or let your AI coding agent ask them one by one (it reads [AGENTS.md](../AGENTS.md)). Short answers are fine; "not sure" is an answer too, the agent will suggest options.

## 1. The space

- **Topic**: where does the live take place? (café, fishing pond, classroom, stadium stand, garden, space station…)
- **Mood**: cosy, funny, energetic, calm, solemn?
- **Main subject** at the top of the frame: a stage, a counter, a big tree, a screen…
- **Host**: will you be on camera, or is the scene the whole picture?

## 2. Viewers

- When someone joins, **who do they become** in the scene? (a customer, a fan, a fish, a student…)
- Who enters: **everyone** who interacts, or only people who chat a **keyword** / send a gift?
- What do they do while waiting? (sit, dance, wander, cheer)

## 3. Gifts

What happens on screen for each level. One gift can trigger several things (walk somewhere, play a move, an effect, a sound, a voice line).

| Level | Coins per gift | What happens |
|---|---|---|
| Small | 1–9 | e.g. the person glows and waves |
| Medium | 10–99 | e.g. walks to the stage and does a move |
| Large | 100+ | e.g. fireworks, camera zoom, the whole crowd cheers |

Any specific gift with its own action? (e.g. Rose = throws a flower)

## 4. Chat

- **Commands**: what can viewers type, and what happens? (e.g. "dance" → dances, "order coffee" → a cup appears)
- **Draws**: a free daily card, fortune, wish or quote by chat?
- Should comments be **read aloud**?

## 5. Progress

- **Titles** by total coins (e.g. Regular → VIP → Legend)?
- **Goals** for the whole room (e.g. every 1,000 likes = something happens)?
- **Leaderboard**: honour seats or a podium for the top gifters?

## 6. Voice and automatic content

The voice is Vietnamese only (two voices: female HoaiMy, male NamMinh).

- What does it say when someone **joins**, sends a **gift**, reaches a **title**?
- **Periodic announcements** (every few minutes) and **prompts** when chat is quiet ("Type dance to join the party!")?

## 7. Assets

- What do you already have: background, characters, effects, music, sound effects?
- Missing ones: generate with AI (see [ASSETS-GUIDE.md](ASSETS-GUIDE.md)), or start with placeholder shapes?
- Art style: photo, 3D, anime, flat cartoon?
- **2D or 3D?** 2D = one background image + character sheets (easy to make beautiful with AI images). 3D = GLB models and a moving camera (free CC0 model packs exist; heavier on the computer).

## 8. Going live

- Which setup: LIVE Studio window capture, OBS → virtual camera → LIVE Studio, or OBS with a stream key? (see [GO-LIVE.md](GO-LIVE.md))
- Live data through TikFinity Desktop or the direct connection?

## What the agent gives back

Before writing any code, the agent sums your answers up as a one-page plan and waits for your OK:

```
Theme: <name> (folder themes/<kebab-name>)
Scene: <background, main subject, where the crowd stands>
Viewers: <who they become, join rule, idle behaviour>
Gifts: small → <steps> · medium → <steps> · large → <steps> · <special gifts>
Chat: <commands> · <draws>
Titles / goals: <list>
Voice: <join / gift / title lines> · periodic: <items> · prompts: <items>
Assets: have <…> · need <…> (prompts ready in ASSETS-GUIDE style)
Live: <setup A / B / C>, <TikFinity / direct>
```
