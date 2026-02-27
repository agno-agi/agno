# PowerPoint Template Custom Skill

## Overview

This skill provides template styling guidance for generating PowerPoint presentations
that match the corporate template bundled with this skill. When you create presentations
using PptxGenJS, apply all color, font, and dimension specifications below to produce
slides that visually match the provided `template.pptx`.

---

## How to Use This Skill

When asked to create a presentation:

1. Read the styling specifications in this document
2. Use PptxGenJS to generate the PPTX file
3. Apply every color, font, and dimension value exactly as specified below
4. Save the output as a `.pptx` file and return its file ID

Do not invent colors or font names. Only use the values documented here.

---

## Template Color Palette

Apply these exact hex values in all generated presentations:

| Role | Hex Value | When to Use |
|------|-----------|-------------|
| Primary (Accent 1) | `{{ACCENT1_HEX}}` | Title backgrounds, key shapes, first data series |
| Secondary (Accent 2) | `{{ACCENT2_HEX}}` | Secondary highlights, second data series |
| Accent 3 | `{{ACCENT3_HEX}}` | Third data series, supporting elements |
| Accent 4 | `{{ACCENT4_HEX}}` | Fourth data series |
| Accent 5 | `{{ACCENT5_HEX}}` | Fifth data series |
| Accent 6 | `{{ACCENT6_HEX}}` | Sixth data series |
| Dark 1 (Body Text) | `{{DK1_HEX}}` | All body text, bullet points |
| Dark 2 (Subtitle Text) | `{{DK2_HEX}}` | Subtitles, secondary labels, captions |
| Light 1 (Background) | `{{LT1_HEX}}` | Slide backgrounds (standard slides) |
| Light 2 | `{{LT2_HEX}}` | Subtle backgrounds, table row fills, dividers |

> **Note for skill packagers**: Replace each `{{PLACEHOLDER}}` with the actual hex
> value extracted from your `template.pptx` before uploading this skill. You can
> extract values by running:
> ```bash
> python template_to_markdown.py template.pptx
> ```
> and copying the Color Palette section values here.

---

## Font Specifications

- **Title Font**: `{{MAJOR_FONT}}` — use for all slide titles and section headers
- **Body Font**: `{{MINOR_FONT}}` — use for all body text, bullets, captions, footnotes

### Typography Scale

| Element | Font | Size | Bold | Color |
|---------|------|------|------|-------|
| Presentation title (title slide) | `{{MAJOR_FONT}}` | 40pt | No | `{{DK2_HEX}}` |
| Slide title | `{{MAJOR_FONT}}` | 28pt | No | `{{DK2_HEX}}` |
| Section header | `{{MAJOR_FONT}}` | 32pt | No | `{{LT1_HEX}}` |
| Body / bullet text | `{{MINOR_FONT}}` | 18pt | No | `{{DK1_HEX}}` |
| Subtitle | `{{MINOR_FONT}}` | 24pt | No | `{{DK2_HEX}}` |
| Caption / footnote | `{{MINOR_FONT}}` | 12pt | No | `{{DK2_HEX}}` |

---

## Slide Dimensions

All slides must use these exact dimensions to match the template:

| Property | Value |
|----------|-------|
| Width | `{{WIDTH_EMU}}` EMU (`{{WIDTH_IN}}"`) |
| Height | `{{HEIGHT_EMU}}` EMU (`{{HEIGHT_IN}}"`) |
| Aspect ratio | `{{ASPECT_RATIO}}` |

In PptxGenJS, the default 10" × 5.625" (16:9) layout matches these values. You do
not need to set dimensions explicitly if using the default PptxGenJS configuration
and the template is standard widescreen.

---

## Slide Layout Reference

Use the appropriate layout style for each slide type:

| Slide Purpose | Layout | Key Styling Notes |
|---------------|--------|-------------------|
| Opening / title slide | Title Slide | Background `{{ACCENT1_HEX}}` or dark; title white or `{{LT1_HEX}}` |
| Content slide | Title and Content | White background; title `{{DK2_HEX}}`; body `{{DK1_HEX}}` |
| Section divider | Section Header | Accent background; large centered white title |
| Two-column comparison | Two Content | Side-by-side content areas with title |
| Free-form / chart-heavy | Title Only | Title bar at top; full content area below |
| Closing / blank | Blank | No placeholders; full custom layout |

---

## PptxGenJS Code Examples

### Title Slide

```javascript
const prs = new PptxGenJS();
const slide = prs.addSlide();

// Dark background for title slide
slide.addShape(prs.ShapeType.rect, {
    x: 0, y: 0, w: "100%", h: "100%",
    fill: { color: "{{ACCENT1_HEX}}" }
});

// Main title
slide.addText("Presentation Title", {
    x: 0.5, y: 2.0, w: 9.0, h: 1.5,
    fontFace: "{{MAJOR_FONT}}",
    fontSize: 40,
    color: "FFFFFF",
    align: "center",
    bold: false
});

// Subtitle
slide.addText("Subtitle or date", {
    x: 0.5, y: 3.7, w: 9.0, h: 0.8,
    fontFace: "{{MINOR_FONT}}",
    fontSize: 24,
    color: "{{ACCENT3_HEX}}",
    align: "center"
});
```

### Standard Content Slide

```javascript
const slide = prs.addSlide();

// Title
slide.addText("Slide Title", {
    x: 0.5, y: 0.3, w: 9.0, h: 0.9,
    fontFace: "{{MAJOR_FONT}}",
    fontSize: 28,
    color: "{{DK2_HEX}}",
    bold: false
});

// Thin accent bar under title
slide.addShape(prs.ShapeType.rect, {
    x: 0.5, y: 1.1, w: 9.0, h: 0.04,
    fill: { color: "{{ACCENT1_HEX}}" },
    line: { color: "{{ACCENT1_HEX}}" }
});

// Body bullet points
slide.addText([
    { text: "First bullet point", options: { bullet: true } },
    { text: "Second bullet point", options: { bullet: true } },
    { text: "Third bullet point", options: { bullet: true } }
], {
    x: 0.5, y: 1.3, w: 9.0, h: 3.8,
    fontFace: "{{MINOR_FONT}}",
    fontSize: 18,
    color: "{{DK1_HEX}}",
    valign: "top"
});
```

### Two-Column Slide

```javascript
const slide = prs.addSlide();

slide.addText("Comparison Title", {
    x: 0.5, y: 0.3, w: 9.0, h: 0.9,
    fontFace: "{{MAJOR_FONT}}",
    fontSize: 28,
    color: "{{DK2_HEX}}"
});

// Left column label
slide.addText("Option A", {
    x: 0.5, y: 1.2, w: 4.3, h: 0.5,
    fontFace: "{{MAJOR_FONT}}",
    fontSize: 20,
    color: "{{ACCENT1_HEX}}",
    bold: true
});

// Left column content
slide.addText("Description of option A...", {
    x: 0.5, y: 1.8, w: 4.3, h: 3.3,
    fontFace: "{{MINOR_FONT}}",
    fontSize: 16,
    color: "{{DK1_HEX}}"
});

// Right column label
slide.addText("Option B", {
    x: 5.2, y: 1.2, w: 4.3, h: 0.5,
    fontFace: "{{MAJOR_FONT}}",
    fontSize: 20,
    color: "{{ACCENT2_HEX}}",
    bold: true
});

// Right column content
slide.addText("Description of option B...", {
    x: 5.2, y: 1.8, w: 4.3, h: 3.3,
    fontFace: "{{MINOR_FONT}}",
    fontSize: 16,
    color: "{{DK1_HEX}}"
});
```

### Chart Slide

```javascript
const slide = prs.addSlide();

slide.addText("Revenue by Quarter", {
    x: 0.5, y: 0.3, w: 9.0, h: 0.9,
    fontFace: "{{MAJOR_FONT}}",
    fontSize: 28,
    color: "{{DK2_HEX}}"
});

// Chart series colors must match the accent palette in order
const chartColors = [
    "{{ACCENT1_HEX}}",  // Series 1
    "{{ACCENT2_HEX}}",  // Series 2
    "{{ACCENT3_HEX}}",  // Series 3
    "{{ACCENT4_HEX}}"   // Series 4
];

slide.addChart(prs.ChartType.bar, [
    {
        name: "Revenue",
        labels: ["Q1", "Q2", "Q3", "Q4"],
        values: [420, 510, 490, 620]
    }
], {
    x: 0.5, y: 1.2, w: 9.0, h: 3.8,
    barDir: "col",
    chartColors: [chartColors[0]],
    showLegend: true,
    legendFontFace: "{{MINOR_FONT}}"
});
```

---

## Reading the Bundled Template File

If you need to extract additional structural or layout information from the template
(e.g., custom slide master backgrounds, complex shape positions), the `template.pptx`
file is available in the skill sandbox:

```python
from pptx import Presentation

prs = Presentation("template.pptx")  # Available in the skill execution sandbox

# Inspect slide layouts
for idx, layout in enumerate(prs.slide_layouts):
    print(f"Layout {idx}: {layout.name}")
    for ph in layout.placeholders:
        print(f"  Placeholder {ph.placeholder_format.idx}: {ph.name}")

# Access theme colors via XML
ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
slide_master = prs.slide_masters[0]
for rel in slide_master.part.rels.values():
    if "theme" in rel.reltype:
        theme_xml = rel.target_part.blob
        break
```

---

## Quality Checklist

Before returning the generated PPTX, verify:

- [ ] All titles use `{{MAJOR_FONT}}` font family
- [ ] All body text uses `{{MINOR_FONT}}` font family
- [ ] Primary accent color `{{ACCENT1_HEX}}` is applied to key shapes or highlights
- [ ] Title text color is `{{DK2_HEX}}`
- [ ] Body text color is `{{DK1_HEX}}`
- [ ] Slide dimensions match `{{WIDTH_EMU}}` x `{{HEIGHT_EMU}}` EMU
- [ ] Chart series colors follow the accent palette order

---

## Packaging This Skill

To bundle this skill with your template file and upload it via the Skills API:

1. Replace all `{{PLACEHOLDER}}` values with real hex/font values from your template:
   ```bash
   python template_to_markdown.py my_template.pptx
   # Copy values from the output into this file
   ```

2. Upload to Anthropic's Skills API:
   ```bash
   # Create a zip with both files
   zip custom_pptx_skill.zip SKILL.md template.pptx

   # Upload via API
   curl -X POST https://api.anthropic.com/v1/skills \
     -H "x-api-key: $ANTHROPIC_API_KEY" \
     -H "anthropic-version: 2023-06-01" \
     -H "anthropic-beta: skills-2025-10-02" \
     -F "file=@custom_pptx_skill.zip" \
     -F "skill_type=code_execution"
   ```

3. Use the returned `skill_id` in your agent configuration:
   ```python
   from agno.models.anthropic import Claude

   model = Claude(
       id="claude-sonnet-4-5-20250929",
       skills=[
           {"type": "anthropic", "skill_id": "pptx", "version": "latest"},  # built-in pptx skill
           {"type": "custom", "skill_id": "<returned-skill-id>", "version": "latest"},  # your template skill
       ],
   )
   ```
