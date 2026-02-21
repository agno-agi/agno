# Architecture: PowerPoint Template Workflow

**File:** `cookbook/90_models/anthropic/skills/powerpoint_template_workflow.py`
**Date:** 2026-02-21
**Pattern:** Sequential Agno Workflow with mixed agent steps and executor functions

---

## Overview

This cookbook implements a **4-step Agno Workflow pipeline** that generates professional PowerPoint presentations by combining AI content generation, AI image creation, and deterministic template assembly. The pipeline takes a user prompt and a `.pptx` template file, producing a final presentation that matches the template's visual style.

The architecture separates concerns into distinct workflow steps:
1. An LLM generates raw slide content
2. A second LLM plans which slides need images
3. An image generation model creates visuals
4. A deterministic function assembles everything onto the template

---

## How It Works (Visual Overview)

This pipeline turns a simple text prompt into a polished PowerPoint presentation in 4 automated steps:

```
                    ┌─────────────────┐
                    │   YOUR INPUTS   │
                    │                 │
                    │  Text Prompt    │
                    │  + Template     │
                    └────────┬────────┘
                             │
                             ▼
        ┌────────────────────────────────────────┐
        │  STEP 1: Content Generation            │
        │                                        │
        │  Agent: Claude (Anthropic)              │
        │  Role:  Writes the presentation         │
        │         content — titles, bullets,      │
        │         tables, and charts              │
        │                                        │
        │  Output: Raw .pptx file with content   │
        └────────────────────┬───────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────┐
        │  STEP 2: Image Planning                │
        │                                        │
        │  Agent: Gemini (Google)                 │
        │  Role:  Reviews each slide and decides  │
        │         which ones need images          │
        │                                        │
        │  Output: Image plan (yes/no per slide) │
        └────────────────────┬───────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────┐
        │  STEP 3: Image Generation              │
        │                                        │
        │  Tool: NanoBanana (Gemini Image Gen)    │
        │  Role:  Creates AI-generated images     │
        │         for the slides that need them   │
        │                                        │
        │  Output: PNG images for selected slides │
        └────────────────────┬───────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────┐
        │  STEP 4: Template Assembly             │
        │                                        │
        │  Engine: Deterministic (no AI)          │
        │  Role:  Takes your template's visual    │
        │         design and maps all content +   │
        │         images onto it                  │
        │                                        │
        │  Output: Final polished .pptx file     │
        └────────────────────┬───────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   YOUR OUTPUT   │
                    │                 │
                    │  Professional   │
                    │  Presentation   │
                    │  (.pptx file)   │
                    └─────────────────┘
```

### Key Actors

| Step | Who Does the Work | What They Do | AI or Code? |
|------|-------------------|--------------|-------------|
| 1 | **Claude** (Anthropic) | Writes all slide content from your prompt | AI Agent |
| 2 | **Gemini** (Google) | Decides which slides benefit from images | AI Agent |
| 3 | **NanoBanana** (Gemini) | Generates professional images for slides | AI Tool |
| 4 | **Template Engine** | Applies your company's template styling | Deterministic Code |

### What You Control

| Option | What It Does | Default |
|--------|-------------|---------|
| `--template` / `-t` | Your company's .pptx template | Required |
| `--prompt` / `-p` | What the presentation should be about | Built-in demo |
| `--output` / `-o` | Where to save the result | `presentation_from_template.pptx` |
| `--no-images` | Skip Steps 2 and 3 (faster, text-only) | Images enabled |
| `--no-stream` | Use simpler API mode (more reliable for short prompts) | Streaming enabled |
| `--verbose` / `-v` | Show detailed diagnostic output | Off |

### Quick Example

```bash
# Generate a presentation about AI trends using your company template
python powerpoint_template_workflow.py \
    --template company_template.pptx \
    --prompt "Create a 5-slide presentation about AI trends in 2026" \
    --output ai_trends.pptx
```

---

## Workflow Data Flow

```mermaid
graph TD
    classDef input fill:#eef2ff,stroke:#6366f1,stroke-width:2px;
    classDef agent fill:#f5f3ff,stroke:#8b5cf6,stroke-width:2px;
    classDef process fill:#f8fafc,stroke:#94a3b8,stroke-width:1px;
    classDef storage fill:#fffbeb,stroke:#f59e0b,stroke-width:2px;
    
    %% Storage and Database Layer
    subgraph DataLayer
        R2[("Cloudflare R2<br/>(Template & Output Object Storage)")]:::storage
        DB[("MongoDB<br/>(Agent State & Metadata Tracking)")]:::storage
    end

    %% Client / Input Layer
    subgraph InputsLayer
        UP["User Prompt"]:::input
        TP["Template .pptx"]:::input
    end

    %% Backend Execution Layer
    subgraph Service
        
        %% Phase 1
        subgraph P1
            BP["_build_prompt_with_template_context()"]:::process
            Agent{"Claude Sonnet 4.6<br/>(PowerPoint Agent with pptx skill)"}:::agent
            FDH["file_download_helper.py"]:::process
            GF["generated_file on disk<br/>(raw .pptx)"]:::process
            
            BP -- "enhanced prompt" --> Agent
            Agent -- "generates raw .pptx" --> FDH
            FDH -- "downloaded .pptx file" --> GF
        end

        %% Phase 2
        subgraph P2
            AT["apply_template()"]:::process
            CT["Copy template to output path"]:::process
            CS["Clear all template slides"]:::process
            Loop{"For each generated slide"}:::process
            ESC["_extract_slide_content()"]:::process
            FBL["_find_best_layout()"]:::process
            PS["_populate_slide()"]:::process
            Save["Save final .pptx"]:::process
            
            AT --> CT --> CS --> Loop
            Loop --> ESC --> FBL --> PS
            PS -- "next slide" --> Loop
            Loop -- "all slides done" --> Save
        end
    end

    Out["Output .pptx"]:::input

    %% Logical Flow Connections
    UP --> BP
    TP --> BP
    TP --> AT
    GF --> AT
    Save --> Out
    
    %% Infrastructure & IO Mapping
    TP -. "Fetched from" .-> R2
    Out -. "Uploaded to" .-> R2
    Service -. "Session & Job State" .-> DB
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `agno` | Agent, Workflow, Step, Claude model, Gemini model, NanoBananaTools |
| `anthropic` | Anthropic API client for downloading skill-generated files |
| `python-pptx` | Presentation reading/writing, shapes, charts, placeholders |
| `lxml` | XML manipulation for removing template slides and shape ID management |
| `pydantic` | Structured output schemas for image planning |
| `pillow` | Required by NanoBananaTools for image handling |

**Local dependency:**
- [`file_download_helper.py`](file_download_helper.py) — Downloads files produced by Claude's `pptx` skill via the Anthropic Files API. Detects file type from magic bytes and saves to disk.

---

## Data Models

### Pydantic Models — Structured Agent Output

| Model | Purpose | Used In |
|-------|---------|---------|
| [`SlideImageDecision`](powerpoint_template_workflow.py) | Per-slide decision: needs image? prompt? reasoning? | Step 2 output |
| [`ImagePlan`](powerpoint_template_workflow.py) | List of `SlideImageDecision` for all slides | Step 2 `output_schema` |

### Dataclasses — Internal Content Representation

| Dataclass | Purpose | Fields |
|-----------|---------|--------|
| [`TableData`](powerpoint_template_workflow.py) | Extracted table with position | `rows`, `left`, `top`, `width`, `height` |
| [`ImageData`](powerpoint_template_workflow.py) | Extracted image blob with position | `blob`, `left`, `top`, `width`, `height`, `content_type` |
| [`ChartExtract`](powerpoint_template_workflow.py) | Extracted chart data with position | `chart_type`, `categories`, `series`, `left`, `top`, `width`, `height` |
| [`SlideContent`](powerpoint_template_workflow.py) | All content from one slide | `title`, `subtitle`, `body_paragraphs`, `tables`, `images`, `charts`, `shapes_xml` |
| [`ContentArea`](powerpoint_template_workflow.py) | Safe content region on a template slide in EMU | `left`, `top`, `width`, `height` |

### Dataclasses — Template Style Extraction

| Dataclass | Purpose | Fields |
|-----------|---------|--------|
| [`TemplateTheme`](powerpoint_template_workflow.py) | Theme colors and fonts from the template's slide master | `accent_colors` (up to 6), `dk1`, `dk2`, `lt1`, `lt2`, `hlink`, `folHlink`, `major_font`, `minor_font` |
| [`TemplateTableStyle`](powerpoint_template_workflow.py) | Table styling extracted from reference tables in the template | `header_font_size`, `header_font_color`, `header_font_family`, `header_fill`, `cell_font_size`, `cell_font_color`, `cell_font_family`, `cell_fill`, `border_color`, `raw_tblPr_xml` |
| [`TemplateChartStyle`](powerpoint_template_workflow.py) | Chart styling extracted from reference charts in the template | `series_fill_colors`, `series_line_colors`, `axis_font_size`, `axis_font_family`, `legend_font_size`, `legend_font_family`, `data_label_font_size`, `plot_area_fill` |
| [`TemplateStyle`](powerpoint_template_workflow.py) | Composite container for all extracted template styling | `theme` (`TemplateTheme`), `table_style` (`TemplateTableStyle`), `chart_style` (`TemplateChartStyle`), `body_font_size`, `title_font_size` |

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

## Step-by-Step Architecture

### Step 1: Content Generation

**Type:** Executor function
**Function:** [`step_generate_content()`](powerpoint_template_workflow.py)
**Agent:** Claude `claude-sonnet-4-5-20250929` with `pptx` skill

**Flow:**
1. Reads the template to extract available layout names
2. Builds an enhanced prompt with structural requirements for template compatibility
3. Creates a Claude `Agent` with the `pptx` skill and formatting instructions
4. Runs the agent (streaming or non-streaming based on `--no-stream` flag), which generates a `.pptx` file server-side
5. Downloads the generated file via [`download_skill_files()`](file_download_helper.py) using the Anthropic Files API
6. Validates the download is a valid `.pptx` file
7. Opens the generated presentation and extracts [`SlideContent`](powerpoint_template_workflow.py) from each slide using [`_extract_slide_content()`](powerpoint_template_workflow.py)
8. Stores extracted data in `session_state` for downstream steps:
   - `generated_file`: path to the downloaded `.pptx`
   - `slides_data`: list of slide metadata dicts
   - `total_slides`: count

**Agent instructions** enforce:
- One clear title per slide
- 4-6 concise bullet points
- Tables limited to 6 rows x 5 columns
- No custom fonts, colors, SmartArt, or animations
- Standard slide ordering: Title, Content, Closing

**Streaming modes:**
- **Streaming (default):** Required for long-running skill operations (>10 min) but may have issues with `provider_data` propagation.
- **Non-streaming (`--no-stream`):** Simpler and more reliable for shorter operations but can timeout on complex presentations.

### Step 2: Image Planning

**Type:** Agent step
**Agent:** [`image_planner`](powerpoint_template_workflow.py) — Gemini `gemini-2.5-flash-image` with `output_schema=ImagePlan`

**Flow:**
1. Receives the JSON summary of slides from Step 1 as input
2. Uses Gemini with structured output to decide per-slide whether an image is needed
3. Outputs an [`ImagePlan`](powerpoint_template_workflow.py) with a list of [`SlideImageDecision`](powerpoint_template_workflow.py)s

**Decision guidelines** encoded in agent instructions:
- Title slides: usually YES
- Data slides with tables/charts: usually NO
- Slides with existing images: ALWAYS NO
- Closing slides: usually NO

### Step 3: Image Generation

**Type:** Executor function
**Function:** [`step_generate_images()`](powerpoint_template_workflow.py)
**Tool:** `NanoBananaTools` with `aspect_ratio="16:9"`

**Flow:**
1. Parses the `ImagePlan` from Step 2
2. Filters out slides that already have images from Claude
3. For each slide needing an image, calls `nano_banana.create_image()` with the prompt
4. Stores generated PNG bytes in `session_state["generated_images"]` keyed by slide index

**Resilience:** Gracefully handles missing `GOOGLE_API_KEY`, unparseable plans, and individual image generation failures without stopping the workflow.

### Step 4: Template Assembly

**Type:** Executor function
**Function:** [`step_assemble_template()`](powerpoint_template_workflow.py)

**Flow:**
1. Copies the template file to the output path
2. Opens the copy as the output presentation
3. **Extracts template styles** via [`_extract_template_styles()`](powerpoint_template_workflow.py) — parses theme colors/fonts and scans reference visual elements (tables, charts) for their styling
4. Removes all existing slides from the template copy using `lxml` XML manipulation
5. For each generated slide:
   a. Extracts content via [`_extract_slide_content()`](powerpoint_template_workflow.py)
   b. Appends any AI-generated image from `session_state` as an [`ImageData`](powerpoint_template_workflow.py)
   c. Selects the best template layout via [`_find_best_layout()`](powerpoint_template_workflow.py)
   d. Creates a new slide from the selected layout
   e. Populates the slide via [`_populate_slide()`](powerpoint_template_workflow.py), passing `template_style` for style-aware content rendering
6. Saves the final presentation

---

## Content Extraction and Assembly Functions

### Extraction

| Function | Purpose |
|----------|---------|
| [`_extract_slide_content()`](powerpoint_template_workflow.py) | Walks all shapes on a slide. Classifies each as table, chart, picture, group, or text. Extracts placeholder text by `idx` — 0=title, 1=subtitle/body, >1=other body. Non-placeholder shapes are captured as raw XML. |

**Shape processing order:**
1. Tables → `TableData`
2. Charts → `ChartExtract`
3. Pictures → `ImageData`
4. Groups → XML clone + recursive image extraction
5. Text frames → title/subtitle/body classification
6. Other shapes → XML clone

### Template Layout Selection

| Function | Purpose |
|----------|---------|
| [`_find_best_layout()`](powerpoint_template_workflow.py) | Heuristic matching of slide position to template layout. Title slide → layout with name containing *title slide*. Last slide → *blank/closing/end*. Content slides → *content/body/text*, then *object/list*, then second layout. |

### Content Area Detection

| Function | Purpose |
|----------|---------|
| [`_get_content_area()`](powerpoint_template_workflow.py) | Derives the safe content region from a template layout's placeholders. Strategy: body placeholder idx=1 first, then any non-title placeholder, then default safe margins at 5%/25%/90%/65% of slide dimensions. All values in EMU. |

### Visual Quality Functions

| Function | Purpose |
|----------|---------|
| [`_fit_to_area()`](powerpoint_template_workflow.py) | Aspect-ratio-preserving scaling. Fits an image within a `ContentArea` and centers it. Returns `left, top, width, height` tuple in EMU. |
| [`_populate_placeholder_with_format()`](powerpoint_template_workflow.py) | Preserves template paragraph/run XML formatting. Captures `pPr` and `rPr` elements from the first template paragraph, clears the text frame, inserts new text with cloned formatting. Enables `word_wrap` and calls `fit_text()` for auto-sizing with fallback to `MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE`. Accepts optional `template_style: TemplateStyle` — when provided, uses theme font names for `fit_text()` instead of the hardcoded default. |

### Transfer Functions

All transfer functions receive a [`ContentArea`](powerpoint_template_workflow.py) to position content within the template's safe region.

| Function | Purpose |
|----------|---------|
| [`_transfer_tables()`](powerpoint_template_workflow.py) | Creates tables within the content area. Multiple tables stack vertically. Header row uses `Pt(11)`, data cells `Pt(10)`. Word wrap enabled on all cells. Accepts optional `template_style: TemplateStyle` — when provided, calls [`_apply_table_style()`](powerpoint_template_workflow.py) to apply reference table styling (fonts, fills, borders, raw `tblPr` XML). |
| [`_transfer_images()`](powerpoint_template_workflow.py) | Adds images scaled and centered within the content area via `_fit_to_area()`. |
| [`_transfer_charts()`](powerpoint_template_workflow.py) | Recreates charts from `CategoryChartData` within the content area. Multiple charts stack vertically. Handles None and non-numeric values. Accepts optional `template_style: TemplateStyle` — when provided, calls [`_apply_chart_style()`](powerpoint_template_workflow.py) to apply reference chart styling (series colors, axis/legend fonts, plot area fill). |
| [`_transfer_shapes()`](powerpoint_template_workflow.py) | Deep-copies raw shape XML to the target slide's `spTree`. Reassigns element IDs to avoid collisions. |

### Slide Assembly Orchestrator

| Function | Purpose |
|----------|---------|
| [`_populate_slide()`](powerpoint_template_workflow.py) | Orchestrates all transfers for a single slide. Computes `ContentArea` from the layout. Fills title placeholder idx=0, body placeholder idx=1, then fallback textboxes if placeholders are missing. Calls all transfer functions. Accepts optional `template_style: TemplateStyle` — passes it to [`_populate_placeholder_with_format()`](powerpoint_template_workflow.py), [`_transfer_tables()`](powerpoint_template_workflow.py), and [`_transfer_charts()`](powerpoint_template_workflow.py). When `template_style` is available, fallback textboxes use theme fonts and colors instead of hardcoded defaults. |

**Placeholder filling priority:**
1. Placeholder idx=0 → title text
2. Placeholder idx=1 → body paragraphs or subtitle
3. Placeholder idx>1 → body paragraphs overflow
4. Fallback textbox at content area position → title or body

---

## Template Style Extraction & Application

### Problem

Visual elements (tables, charts, textboxes) created during template assembly used hardcoded styling — fixed font names, fixed colors, fixed sizes. This produced output that looked disconnected from the template's actual design language, even though the slide layouts matched correctly.

### Solution

Extract styling from the template itself (theme XML + reference visual elements) at the start of Step 4 and apply it to newly created elements. This ensures that tables, charts, and text created by the pipeline inherit the template's visual identity.

### Extraction Pipeline

[`_extract_template_styles()`](powerpoint_template_workflow.py) is the master orchestrator. It opens the template presentation and calls three specialized extractors, plus extracts placeholder font sizes from the slide master:

| Function | What It Extracts | How |
|----------|-----------------|-----|
| [`_extract_theme_from_prs()`](powerpoint_template_workflow.py) | Theme colors and fonts → [`TemplateTheme`](powerpoint_template_workflow.py) | Navigates slide master → theme part, parses `clrScheme` for accent/dk/lt/hyperlink colors and `fontScheme` for major/minor font names |
| [`_extract_table_styles_from_prs()`](powerpoint_template_workflow.py) | Table styling → [`TemplateTableStyle`](powerpoint_template_workflow.py) | Scans all template slides for tables, extracts header/cell font sizes, colors, families, fills, borders, and raw `tblPr` XML from the first table found |
| [`_extract_chart_styles_from_prs()`](powerpoint_template_workflow.py) | Chart styling → [`TemplateChartStyle`](powerpoint_template_workflow.py) | Scans all template slides for charts, extracts series fill/line colors, axis/legend/data-label font properties, and plot area fill from the first chart found |
| *(inline in orchestrator)* | Placeholder font sizes → `body_font_size`, `title_font_size` | Inspects slide master placeholders for `idx=0` (title) and `idx=1` (body) default font sizes |

### Application Pipeline

The extracted [`TemplateStyle`](powerpoint_template_workflow.py) is passed from [`step_assemble_template()`](powerpoint_template_workflow.py) → [`_populate_slide()`](powerpoint_template_workflow.py) → downstream functions:

| Function | What It Applies |
|----------|----------------|
| [`_apply_table_style()`](powerpoint_template_workflow.py) | Deep-copies `tblPr` XML from the reference table, applies header/cell font sizes, colors, families, fills, and borders to every cell in the new table |
| [`_apply_chart_style()`](powerpoint_template_workflow.py) | Applies series fill/line colors, axis and legend font properties, and plot area fill to newly created charts |
| [`_populate_placeholder_with_format()`](powerpoint_template_workflow.py) | Uses theme font names for `fit_text()` calls instead of the hardcoded `"Calibri"` default |
| [`_populate_slide()`](powerpoint_template_workflow.py) | Uses theme fonts and colors for fallback textboxes (title and body) when no placeholder match is found |

### Style Priority Cascade

The system follows a three-tier priority cascade to determine what styling to apply:

```
Priority 1: Reference template visual elements (highest)
  └─ When the template contains a table/chart, its styling is extracted
     and applied verbatim to new elements of the same type.

Priority 2: Theme colors and fonts (secondary)
  └─ When no matching reference element exists, theme accent colors
     are used for fills and theme font names for text rendering.

Priority 3: Hardcoded defaults (fallback, backwards compatible)
  └─ When no template_style is available (e.g., template has no theme),
     the original hardcoded values are used — Calibri, Pt(11), etc.
```

This cascade ensures **backwards compatibility**: if the template lacks a theme or reference elements, the pipeline behaves exactly as before.

### Extraction and Application Flow

```mermaid
flowchart TD
    subgraph Extraction["Style Extraction (start of Step 4)"]
        TP["Template .pptx"] --> ETS["_extract_template_styles()"]
        ETS --> ETH["_extract_theme_from_prs()"]
        ETS --> ETAB["_extract_table_styles_from_prs()"]
        ETS --> ECH["_extract_chart_styles_from_prs()"]
        ETS --> EPH["Placeholder font extraction"]
        ETH --> TT["TemplateTheme"]
        ETAB --> TTS["TemplateTableStyle"]
        ECH --> TCS["TemplateChartStyle"]
        EPH --> FS["body/title font sizes"]
        TT --> TS["TemplateStyle"]
        TTS --> TS
        TCS --> TS
        FS --> TS
    end

    subgraph Application["Style Application (per slide)"]
        TS --> PS["_populate_slide(template_style)"]
        PS --> PPF["_populate_placeholder_with_format(template_style)"]
        PS --> TRB["_transfer_tables(template_style)"]
        PS --> TRC["_transfer_charts(template_style)"]
        PS --> FTB["Fallback textboxes (themed fonts/colors)"]
        TRB --> ATS["_apply_table_style()"]
        TRC --> ACS["_apply_chart_style()"]
    end

    style Extraction fill:#f0f9ff,stroke:#3b82f6,stroke-width:2px
    style Application fill:#fefce8,stroke:#eab308,stroke-width:2px
```

---

## Session State Schema

The `session_state` dict is shared across all workflow steps:

```python
session_state = {
    # Set at workflow creation from CLI args
    "template_path": str,       # Path to the .pptx template file
    "output_dir": str,          # Directory for intermediate files
    "output_path": str,         # Final output .pptx path
    "verbose": bool,            # Enable verbose/debug logging
    "stream": bool,             # Use streaming mode for Claude agent

    # Set by Step 1
    "generated_file": str,      # Path to Claude-generated .pptx
    "slides_data": list,        # List of slide metadata dicts
    "total_slides": int,        # Number of slides

    # Set by Step 3
    "generated_images": dict,   # {slide_index: PNG bytes}
}
```

---

## CLI Interface

**Function:** [`parse_args()`](powerpoint_template_workflow.py)

| Flag | Short | Required | Default | Description |
|------|-------|----------|---------|-------------|
| `--template` | `-t` | Yes | — | Path to `.pptx` template file |
| `--output` | `-o` | No | `presentation_from_template.pptx` | Output filename |
| `--prompt` | `-p` | No | Built-in 6-slide demo | Custom presentation prompt |
| `--no-images` | — | No | `False` | Skip Steps 2 and 3 entirely |
| `--no-stream` | — | No | `False` | Disable streaming mode for Claude agent (more reliable for shorter prompts, but may timeout on complex presentations) |
| `--verbose` | `-v` | No | `False` | Enable verbose/debug logging for troubleshooting |

**Usage examples:**

```bash
# Basic usage with template
.venvs/demo/bin/python cookbook/90_models/anthropic/skills/powerpoint_template_workflow.py \
    --template my_template.pptx

# Custom prompt and output
.venvs/demo/bin/python cookbook/90_models/anthropic/skills/powerpoint_template_workflow.py \
    -t my_template.pptx -o report.pptx -p "Create a 5-slide AI trends presentation"

# Skip image generation
.venvs/demo/bin/python cookbook/90_models/anthropic/skills/powerpoint_template_workflow.py \
    -t my_template.pptx --no-images

# Disable streaming (more reliable for short prompts)
.venvs/demo/bin/python cookbook/90_models/anthropic/skills/powerpoint_template_workflow.py \
    -t my_template.pptx --no-stream

# Verbose logging for debugging
.venvs/demo/bin/python cookbook/90_models/anthropic/skills/powerpoint_template_workflow.py \
    -t my_template.pptx -v
```

---

## Workflow Construction

The workflow is conditionally assembled based on CLI flags:

```mermaid
flowchart LR
    S1[Step 1: Content Generation<br>executor=step_generate_content<br>stream or non-stream mode]
    S2[Step 2: Image Planning<br>agent=image_planner]
    S3[Step 3: Image Generation<br>executor=step_generate_images]
    S4[Step 4: Template Assembly<br>executor=step_assemble_template]

    S1 --> S2 --> S3 --> S4

    style S2 stroke-dasharray: 5 5
    style S3 stroke-dasharray: 5 5
```

*Dashed steps are skipped when `--no-images` is used.*

| Step | Name | Type | Executor/Agent |
|------|------|------|----------------|
| 1 | Content Generation | `executor` | `step_generate_content` (streaming or non-streaming based on `--no-stream`) |
| 2 | Image Planning | `agent` | `image_planner` - Gemini with `output_schema` |
| 3 | Image Generation | `executor` | `step_generate_images` |
| 4 | Template Assembly | `executor` | `step_assemble_template` |

**Agno Workflow wiring** in the `__main__` block:
- Each `Step` can have either an `agent` or an `executor` — not both
- Agent steps pass `step_input.previous_step_content` as the prompt
- Executor steps receive `(step_input, session_state)` and return `StepOutput`
- `session_state` is shared across all steps for passing large data like file paths and image bytes

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes | Claude agent and Anthropic Files API |
| `GOOGLE_API_KEY` | For images | Gemini image planner and NanoBananaTools image generation |

---

## Key Design Decisions

### Why Workflow over Team?

The pipeline is **strictly sequential** — each step depends on the previous step's output. A Workflow with ordered Steps is the natural fit. A Team-based approach would add coordination overhead without benefit since there is no parallelism or dynamic delegation.

### Why Mixed Agent + Executor Steps?

- **Steps 1 and 2** involve LLM reasoning and benefit from Agno Agent abstractions
- **Steps 3 and 4** are primarily procedural: calling an API in a loop and manipulating python-pptx objects. Executor functions give full control over error handling and session state management.

### Why Deterministic Template Assembly?

The template assembly step is entirely deterministic — no LLM is involved. This is intentional because:
- LLMs generating python-pptx code introduce non-determinism
- Visual quality rules like `fit_text()`, content area positioning, and font sizing must always be applied
- Deterministic assembly is testable and predictable

### Why ContentArea-Based Positioning?

Content extracted from Claude's generated slides has EMU positions specific to Claude's default slide dimensions. Transferring these raw values to a different template causes misalignment, overflow, and clipping. The `ContentArea` abstraction normalizes positioning by deriving safe bounds from the template's own placeholders. See [`DESIGN_visual_quality.md`](DESIGN_visual_quality.md) for the full design rationale.

---

## File Organization

```
cookbook/90_models/anthropic/skills/
    powerpoint_template_workflow.py    # This file — the 4-step workflow
    agent_with_powerpoint_template.py  # Simpler single-agent version
    file_download_helper.py            # Shared: downloads skill-generated files
    my_template.pptx                   # Sample template
    my_template1.pptx                  # Alternate sample template
    DESIGN_visual_quality.md           # Design doc for visual quality fixes
    ARCHITECTURE_powerpoint_template_workflow.md  # This architecture doc
    README.md                          # Cookbook README
    TEST_LOG.md                        # Test results log
```

---

## Related Documents

- [`DESIGN_visual_quality.md`](DESIGN_visual_quality.md) — Detailed design for the `ContentArea`-based visual quality improvements and Phase 2 Team-based refactor proposal
- [`agent_with_powerpoint_template.py`](agent_with_powerpoint_template.py) — Simpler single-agent variant that shares the same extraction and assembly functions
