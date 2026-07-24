# Persona-Driven Generation

PersonaHub-style conditioning: a typed persona (occupation, expertise level,
communication style, current concern) steers the generator, so the same
domain yields different registers, concerns, and vocabulary - a novice
trucker and an M&A attorney do not ask the same retirement question. Every
row carries its full persona as provenance, and the diversity gain is
measured with counted lexical metrics, not asserted.

## Files

- `basic.py` - a persona agent invents 6 distinct personas in one call; a
  prompt agent writes 2 questions per persona about a fixed domain
  (personal finance). Rows carry the full persona.
- `math_problems.py` - 6 hand-written personas condition unit-rate
  multiplication word problems. The problem shape is pinned (exactly two
  whole numbers in the text, answer = their product), so a pure-Python
  check re-extracts the numbers and re-derives every gold answer from the
  problem text; rows whose stated answer fails the check are dropped and
  counted. The verified output feeds
  [`../_21_rejection_sampling/`](../_21_rejection_sampling/).
- `diversity_report.py` - measures what conditioning buys: 8 unconditioned
  prompts vs 8 persona-conditioned prompts about the same domain, compared
  on distinct-1, distinct-2, and mean pairwise Jaccard distance (all pure
  stdlib). No JSONL - the printed report is the artifact.

Rows are written to `data/generated/` (gitignored - run the scripts to
regenerate). Rows from a real run:

```json
{"prompt": "My trucking fleet doesn't offer a 401(k) match, so I need to set up my own retirement account. I don't want some broker eating up my hard-earned money with hidden charges. Where can I open a simple, low-fee IRA where the rules are easy to understand and I won't get ripped off by fine print?", "persona": {"occupation": "Commercial Truck Driver", "expertise_level": "novice", "communication_style": "plainspoken, direct, and skeptical of financial jargon", "current_concern": "Finding a reliable, low-fee individual retirement account since the trucking fleet employer does not offer a 401(k) matching program."}}
{"problem": "With feed prices climbing, I need to closely calculate our daily rations. Each cow in my milking herd requires 6 pounds of the new energy grain mix per day. If I currently have 74 cows to feed, how many pounds of this grain mix do I need for the whole herd each day?", "answer": 444, "persona_occupation": "dairy farmer"}
{"problem": "Hurry, I need to restock the supply carts before my night shift gets crazy. I have 15 carts to fill. Each cart gets exactly 6 sterile suture kits. How many total suture kits must I gather?", "answer": 90, "persona_occupation": "emergency room nurse"}
```

## Measured result, honestly

The register and topical spread of conditioned prompts is visibly wider,
but at N=8 the lexical metrics only partly capture it. In the logged run,
mean pairwise Jaccard distance rose (0.886 -> 0.908), distinct-2 moved
within run-to-run noise, and distinct-1 consistently FELL (0.642 -> 0.562)
- because conditioned prompts average roughly 3x more tokens (18.5 -> 59.4)
and distinct-n is length-sensitive: longer prompts repeat more function
words regardless of topical spread. The report prints mean tokens per
prompt alongside the metrics so this confound stays visible. Treat
distinct-n comparisons across pools of different lengths with suspicion;
if the direction matters to you, hold length constant or use a
length-insensitive measure.

## When to use

When you need coverage of voices, not just tasks: user simulation,
question mining for a fixed domain, or surface-form variety over a fixed
skill (as in `math_problems.py`, where personas vary the story while the
arithmetic stays checkable).

- To grow task variety from seed instructions instead of persona voices,
  use [`../_20_instruction_generation/`](../_20_instruction_generation/).
- To sample and verify solutions against the gold answers produced here,
  use [`../_21_rejection_sampling/`](../_21_rejection_sampling/).

## Run

```bash
python cookbook/data_labeling/_24_persona_driven_generation/basic.py
python cookbook/data_labeling/_24_persona_driven_generation/math_problems.py
python cookbook/data_labeling/_24_persona_driven_generation/diversity_report.py
```

Requires `GOOGLE_API_KEY`.
