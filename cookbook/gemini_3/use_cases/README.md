# Use Cases

Domain-specific examples that combine multiple steps from the main guide. Each script demonstrates how to compose Agno agents for real-world scenarios in music, film, and gaming.

## Examples

| File | Domain | Steps Combined | What It Does |
|:-----|:-------|:---------------|:-------------|
| `music_asset_brief.py` | Music | Audio + Image + Search + Structured Output | Analyzes a track and album art, researches the artist, produces a structured brief |
| `film_scene_breakdown.py` | Film | Video + PDF + Team | Analyzes a video clip, reads a script PDF, and uses a team to produce a scene breakdown |
| `game_concept_pitch.py` | Gaming | Image Gen + Structured Output + Team | Generates concept art, structures a game pitch, and uses a team for review |

## Running

```bash
# Make sure you've completed the Fast Path setup from the main README
python cookbook/gemini_3/use_cases/music_asset_brief.py
python cookbook/gemini_3/use_cases/film_scene_breakdown.py
python cookbook/gemini_3/use_cases/game_concept_pitch.py
```

## Adapting to Your Domain

These are starting points. To adapt for your use case:

1. Swap the sample prompts and data for your own
2. Adjust the output schemas to match your data model
3. Add or remove agents from the team based on your workflow
4. Connect to your own knowledge bases for domain expertise
