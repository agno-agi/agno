# Architecture: Agent with PowerPoint Template

**File:** `cookbook/90_models/anthropic/skills/agent_with_powerpoint_template.py`
**Date:** 2026-02-19
**Pattern:** Single Agno Agent + deterministic post-processing (2-phase pipeline)

---

## Overview

This cookbook implements a **2-phase pipeline** that generates a PowerPoint presentation using a single Claude agent and then applies a custom template via deterministic Python code. It is the simpler counterpart to the [workflow version](ARCHITECTURE_powerpoint_template_workflow.md), omitting image planning/generation steps entirely.

The architecture cleanly separates AI content generation from template assembly:
1. A Claude agent with the `pptx` skill generates a raw `.pptx` file
2. Pure Python code extracts all content and transfers it onto the template's layouts

**Key difference from the workflow version:** No image planning or generation steps. No Gemini or NanoBanana integration. Single agent, 2 phases, simpler flow.

---

## 2-Phase Pipeline

```mermaid
flowchart TD
    subgraph Inputs
        UP[User Prompt]
        TPL[Template .pptx]
    end

    subgraph Phase1[Phase 1: Content Generation]
        BPC[_build_prompt_with_template_context]
        AGT[powerpoint_agent - Claude with pptx skill]
        DL[file_download_helper.py]
        UP --> BPC
        TPL --> BPC
        BPC -->|enhanced prompt| AGT
        AGT -->|generates raw .pptx| DL
        DL -->|downloaded .pptx file| GF[generated_file on disk]
    end

    subgraph Phase2[Phase 2: Template Application]
        AT[apply_template]
        CP[Copy template to output path]
        CLR[Clear all template slides]
        LOOP[For each generated slide]
        EX[_extract_slide_content]
        FL[_find_best_layout]
        PS[_populate_slide]
        SV[Save final .pptx]

        AT --> CP --> CLR --> LOOP
        LOOP --> EX --> FL --> PS
        PS -->|next slide| LOOP
        LOOP -->|all slides done| SV
    end

    GF --> Phase2
    TPL --> Phase2
    SV --> OUT[Output .pptx]
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `agno` | Agent framework, Claude model wrapper |
| `anthropic` | Anthropic API client for downloading skill-generated files |
| `python-pptx` | Presentation reading/writing, shapes, charts, placeholders |
| `lxml` | XML manipulation for removing template slides and shape ID management |

**Local dependency:**
- [`file_download_helper.py`](file_download_helper.py) — Downloads files produced by Claude's `pptx` skill via the Anthropic Files API. Detects file type from magic bytes and saves to disk.

---

## Data Models

All data models are `dataclasses` used internally for content extraction and transfer.

| Dataclass | Purpose | Fields |
|-----------|---------|--------|
| [`TableData`](agent_with_powerpoint_template.py:44) | Extracted table with EMU position | `rows`, `left`, `top`, `width`, `height` |
| [`ImageData`](agent_with_powerpoint_template.py:55) | Extracted image blob with EMU position | `blob`, `left`, `top`, `width`, `height`, `content_type` |
| [`ChartExtract`](agent_with_powerpoint_template.py:67) | Extracted chart data with EMU position | `chart_type`, `categories`, `series`, `left`, `top`, `width`, `height` |
| [`SlideContent`](agent_with_powerpoint_template.py:79) | All content from one slide | `title`, `subtitle`, `body_paragraphs`, `tables`, `images`, `charts`, `shapes_xml` |
| [`ContentArea`](agent_with_powerpoint_template.py:92) | Safe content region on a template slide in EMU | `left`, `top`, `width`, `height` |

**Data flow through the pipeline:**

```mermaid
flowchart LR
    GS[Generated Slide] -->|_extract_slide_content| SC[SlideContent]
    SC -->|title + bullets + tables + charts + images + shapes_xml| PS[_populate_slide]
    TL[Template Layout] -->|_get_content_area| CA[ContentArea]
    CA --> PS
    PS --> NS[New Slide on Template]
```

---

## Phase 1: Content Generation

### Prompt Enhancement

**Function:** [`_build_prompt_with_template_context()`](agent_with_powerpoint_template.py:797)

1. Opens the template `.pptx` and reads all available layout names
2. Appends structural guidance to the user prompt:
   - One clear title + concise bullets per slide
   - No custom fonts, colors, or theme styling
   - Tables and charts are supported with size limits
   - Available layout names from the template
   - Standard slide ordering: Title, Content, Closing

### Agent Definition

**Object:** [`powerpoint_agent`](agent_with_powerpoint_template.py:838)

| Property | Value |
|----------|-------|
| `name` | `PowerPoint Creator` |
| `model` | `Claude` with `id=claude-sonnet-4-5-20250929` |
| `skills` | `pptx` skill via Anthropic skill system |
| `markdown` | `True` |

**Agent instructions** enforce:
- One clear, descriptive title per slide mapped to the title placeholder
- 4-6 concise bullet points per slide, max ~15 words each
- Single short line for subtitle text on title slides
- Tables limited to 6 rows x 5 columns
- Bar, column, line, or pie charts for data visualization
- No custom fonts, colors, SmartArt, animations, or speaker notes
- Visual elements positioned in center/lower portion

### File Download

After the agent runs, the generated `.pptx` is downloaded from the Anthropic Files API using [`download_skill_files()`](file_download_helper.py:34). The main block validates each downloaded file by attempting to open it with `Presentation()`, falling back to extension-agnostic validation if no `.pptx` extension is found.

---

## Phase 2: Template Application

### Entry Point

**Function:** [`apply_template()`](agent_with_powerpoint_template.py:711)

**Flow:**
1. Copy the template file to the output path via `shutil.copy2()`
2. Open the copy as the output presentation
3. Remove all existing slides using `lxml` XML manipulation on `_sldIdLst`
4. For each generated slide:
   a. Extract content via [`_extract_slide_content()`](agent_with_powerpoint_template.py:238)
   b. Select the best template layout via [`_find_best_layout()`](agent_with_powerpoint_template.py:107)
   c. Create a new slide from the selected layout
   d. Populate the slide via [`_populate_slide()`](agent_with_powerpoint_template.py:620)
5. Save the final presentation

---

## Content Extraction and Assembly Functions

### Extraction

| Function | Line | Purpose |
|----------|------|---------|
| [`_extract_slide_content()`](agent_with_powerpoint_template.py:238) | 238 | Walks all shapes on a slide. Classifies each as table, chart, picture, group, or text. Extracts placeholder text by `idx` — 0=title, 1=subtitle/body, >1=other body. Non-placeholder shapes are captured as raw XML. |

**Shape processing order:**
1. Tables → `TableData`
2. Charts → `ChartExtract`
3. Pictures → `ImageData`
4. Groups → XML clone + recursive image extraction from nested shapes
5. Text frames → title/subtitle/body classification by placeholder `idx`
6. Other non-placeholder shapes → XML clone

### Template Layout Selection

| Function | Line | Purpose |
|----------|------|---------|
| [`_find_best_layout()`](agent_with_powerpoint_template.py:107) | 107 | Heuristic matching of slide position to template layout name keywords. |

**Heuristic rules:**
- **Title slide** (index 0) → layout name containing *title slide*, then any *title*, then first layout
- **Last slide** → layout name containing *blank*, *closing*, or *end*
- **Content slides** → *content*, *body*, *text*, then *object*, *list*, then second layout

### Content Area Detection

| Function | Line | Purpose |
|----------|------|---------|
| [`_get_content_area()`](agent_with_powerpoint_template.py:169) | 169 | Derives the safe content region from a template layout's placeholders. |

**Strategy:**
1. Body placeholder `idx=1` → use its exact position
2. Any non-title placeholder `idx > 0` → use its position
3. Default safe margins → 5% left, 25% top, 90% width, 65% height of slide dimensions

### Visual Quality Functions

| Function | Line | Purpose |
|----------|------|---------|
| [`_fit_to_area()`](agent_with_powerpoint_template.py:208) | 208 | Aspect-ratio-preserving scaling. Fits dimensions within a `ContentArea` and centers the result. Returns `left, top, width, height` tuple in EMU. |
| [`_populate_placeholder_with_format()`](agent_with_powerpoint_template.py:392) | 392 | Preserves template paragraph/run XML formatting. Captures `pPr` and `rPr` elements from the first template paragraph, clears the text frame, inserts new text with cloned formatting. Enables `word_wrap` and calls `fit_text()` for auto-sizing with fallback to `MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE`. |

### Transfer Functions

All transfer functions receive a [`ContentArea`](agent_with_powerpoint_template.py:92) to position content within the template's safe region.

| Function | Line | Purpose |
|----------|------|---------|
| [`_transfer_tables()`](agent_with_powerpoint_template.py:476) | 476 | Creates tables within the content area. Multiple tables stack vertically. Header row uses `Pt(11)`, data cells `Pt(10)`. Word wrap enabled on all cells. |
| [`_transfer_images()`](agent_with_powerpoint_template.py:528) | 528 | Adds images scaled and centered within the content area via `_fit_to_area()`. |
| [`_transfer_charts()`](agent_with_powerpoint_template.py:542) | 542 | Recreates charts from `CategoryChartData` within the content area. Multiple charts stack vertically. Handles None and non-numeric values gracefully. |
| [`_transfer_shapes()`](agent_with_powerpoint_template.py:598) | 598 | Deep-copies raw shape XML to the target slide's `spTree`. Reassigns element IDs by finding max existing ID and incrementing to avoid collisions. |

### Slide Assembly Orchestrator

| Function | Line | Purpose |
|----------|------|---------|
| [`_populate_slide()`](agent_with_powerpoint_template.py:620) | 620 | Orchestrates all transfers for a single slide. Computes `ContentArea` from the layout. Fills placeholders, then fallback textboxes, then visual elements. |

**Placeholder filling priority:**
1. Placeholder `idx=0` → title text
2. Placeholder `idx=1` → body paragraphs or subtitle
3. Placeholder `idx>1` → body paragraphs overflow
4. Fallback textbox at content area position → title with `Pt(28)` bold or body with `Pt(18)` + `fit_text()`

**Visual element transfer order:**
1. Tables → `_transfer_tables()`
2. Images → `_transfer_images()`
3. Charts → `_transfer_charts()`
4. Shapes → `_transfer_shapes()`

---

## CLI Interface

**Function:** [`parse_args()`](agent_with_powerpoint_template.py:881)

| Flag | Short | Required | Default | Description |
|------|-------|----------|---------|-------------|
| `--template` | `-t` | Yes | — | Path to `.pptx` template file |
| `--output` | `-o` | No | `presentation_from_template.pptx` | Output filename |
| `--prompt` | `-p` | No | Built-in 6-slide demo | Custom presentation prompt |

**Usage examples:**

```bash
# Basic usage with template
.venvs/demo/bin/python cookbook/90_models/anthropic/skills/agent_with_powerpoint_template.py \
    --template my_template.pptx

# Custom prompt and output
.venvs/demo/bin/python cookbook/90_models/anthropic/skills/agent_with_powerpoint_template.py \
    -t my_template.pptx -o report.pptx -p "Create a 5-slide AI trends presentation"
```

**Default prompt** generates a 6-slide business presentation:
1. Title Slide — Strategic Overview 2026
2. Market Analysis — text with bullets
3. Financial Performance — includes a table
4. Revenue Trends — includes a bar chart
5. Strategic Priorities — text with bullets
6. Closing — Next Steps

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes | Claude agent and Anthropic Files API for file download |

---

## Key Design Decisions

### Why Single Agent over Workflow?

This cookbook targets the **simplest viable architecture** for template-based presentation generation. When image generation is not needed, the overhead of a multi-step Workflow with session state management is unnecessary. A single agent call followed by deterministic post-processing is sufficient.

### Why Deterministic Template Assembly?

The template assembly is entirely deterministic — no LLM is involved. This is intentional because:
- LLMs generating python-pptx code introduce non-determinism
- Visual quality rules like `fit_text()`, content area positioning, and font sizing must always be applied
- Deterministic assembly is testable and predictable

### Why ContentArea-Based Positioning?

Content extracted from Claude's generated slides has EMU positions specific to Claude's default slide dimensions. Transferring these raw values to a different template causes misalignment, overflow, and clipping. The `ContentArea` abstraction normalizes positioning by deriving safe bounds from the template's own placeholders. See [`DESIGN_visual_quality.md`](DESIGN_visual_quality.md) for the full design rationale.

### Why Prompt Enhancement?

[`_build_prompt_with_template_context()`](agent_with_powerpoint_template.py:797) inspects the template before the agent runs, injecting layout names and structural constraints into the prompt. This improves the mapping quality during Phase 2 since the agent generates content that aligns with the template's actual placeholder structure.

---

## Comparison with Workflow Version

| Aspect | Agent Version | Workflow Version |
|--------|---------------|------------------|
| **File** | `agent_with_powerpoint_template.py` | `powerpoint_template_workflow.py` |
| **Architecture** | 2-phase pipeline | 4-step Agno Workflow |
| **LLM calls** | 1 - Claude for content | 2 - Claude for content + Gemini for image planning |
| **Image generation** | None | NanoBananaTools with Gemini |
| **State management** | Local variables in `__main__` | Workflow `session_state` dict |
| **Agno pattern** | `Agent` only | `Workflow` + `Step` + `Agent` |
| **Dependencies** | agno, anthropic, python-pptx, lxml | + pydantic, pillow, google-genai |
| **Required env vars** | `ANTHROPIC_API_KEY` | + `GOOGLE_API_KEY` |

---

## File Organization

```
cookbook/90_models/anthropic/skills/
    agent_with_powerpoint_template.py   # This file — single-agent 2-phase pipeline
    powerpoint_template_workflow.py     # Full 4-step workflow version
    file_download_helper.py             # Shared: downloads skill-generated files
    my_template.pptx                    # Sample template
    my_template1.pptx                   # Alternate sample template
    DESIGN_visual_quality.md            # Design doc for visual quality fixes
    ARCHITECTURE_agent_with_powerpoint_template.md   # This architecture doc
    ARCHITECTURE_powerpoint_template_workflow.md      # Workflow architecture doc
    README.md                           # Cookbook README
    TEST_LOG.md                         # Test results log
```

---

## Related Documents

- [`ARCHITECTURE_powerpoint_template_workflow.md`](ARCHITECTURE_powerpoint_template_workflow.md) — Architecture for the full 4-step workflow version with image planning and generation
- [`DESIGN_visual_quality.md`](DESIGN_visual_quality.md) — Detailed design for the `ContentArea`-based visual quality improvements
- [`file_download_helper.py`](file_download_helper.py) — Shared utility for downloading Anthropic skill-generated files
