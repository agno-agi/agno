TODO:
###


For the current logic in "powerpoint_template_workflow.py" what I can see if I request for typically 10 slides or more presentation file from Claude. It doesn't work. But if I try something like 3, 5, 7 slides presentation files, then it works most of the time. So, I have some thoughts of how to handle this situation so that it will always work,

1. Once user enters his query or prompt with "-p" command, we will first do query optimization and enhancment. Consider tonality, branding, styling, data context etc. properly. Don't overthink or be too creative.
2. Decide how many slides to be generated for the presentation file. This number can be either mentioned in side the user prompt or need to be decided by the llm targeing a optimum no. of slides
3. Next create a storyboard spread across separate markdown file mapped to each slide to be created. There should be a contnutation of the markdown contents for each file in a way that overall tonality, branding, styling, data context etc. should not be lost. Or we may think about a global, common markdown file to avoid any repeatations for any common context information applicable to all slides. Take your best judgment and approach.
4. Use a configurable/command line argument based chunk size (default 3) to decide how many times we will call Claude API to give us the PPTX files. Add max 2 retries for each claude call. I think Agno may have some inbuilt support, but anyway you can check and decide the best approach. Also, put a exponential delay between each normal chunk based calls with base value of 1000ms
5. Once all the files get created (if any internal claude api failure happens even after 2 retries, just log or print, but continue the flow), go for running the remaining steps like template based generation steps, image planning & generation etc. except the last visual step inspection. Generate the transformed files (template, image etc.) for each chunk run.
6. Now, based on the command line argument passed do visual inspection for each file's slides generated based on chunk based loop. If any changes needed, apply that change to the PPTX file, otherwise skip for next pptx file. While applying the required change, if you think relevant function logic is missing in python, then just log it in console irrespective of verbose mode with a suggestion that logic to be added. If you make any change to a particular slide, you also need to verify if that change is proper or any further change is needed. For any change do this inspection upto max 3 times revision. If still not satisfied, just stop and log the issue with a warning message of missing logic to be added later.
7. Finally merge all the PPTX files to the final output pptx file

Note - If template file argument not passed, step 5 and 6 can be skipped. Only step 7 will be executed at the end.

---

## IMPLEMENTATION STATUS

**File:** `powerpoint_chunked_workflow.py`
**Status:** COMPLETED
**Date:** 2026-02-27

### What Was Implemented

The TODO items above have been fully implemented in `powerpoint_chunked_workflow.py`:

1. **Query Optimization** (DONE) — `step_optimize_and_plan()` uses `query_optimizer` agent with `output_schema=StoryboardPlan` to enhance prompt, decide slide count, and generate per-slide storyboard with tonality/branding/styling/data context.

2. **Slide Count Decision** (DONE) — The `StoryboardPlan` model includes `total_slides` field; LLM honors explicit counts in user prompts, otherwise decides optimal count (typically 8-15 for professional decks).

3. **Per-Slide Storyboard Markdown** (DONE) — `step_optimize_and_plan()` writes:
   - `{output_dir}/storyboard/global_context.md` — shared brand/tone/context
   - `{output_dir}/storyboard/slide_NNN.md` — per-slide content plan

4. **Chunked Claude API Calls** (DONE) — `generate_chunk_pptx()` with `--chunk-size` CLI arg (default 3), `--max-retries` (default 2), exponential backoff (base 1000ms).

5. **Retry + Continue on Failure** (DONE) — Failed chunks are logged and skipped; pipeline continues to produce partial presentation.

6. **Per-Chunk Pipeline** (DONE) — `step_process_chunks()` runs template assembly + image planning/generation per chunk independently.

7. **Visual Inspection Per Chunk** (DONE) — `step_visual_review_chunks()` with up to 3 passes per chunk; missing fix functions logged to console regardless of verbose mode.

8. **PPTX Merge** (DONE) — `merge_pptx_files()` uses OPC-relationship-aware `_clone_slide()` to properly transfer images/charts; `step_merge_chunks()` assembles final output.

### How to Run

```bash
# Basic usage (no template, 10 slides, chunk size 3)
.venvs/demo/bin/python cookbook/90_models/anthropic/skills/powerpoint_workflow_demo/powerpoint_chunked_workflow.py \
  -p "Create a 10-slide presentation on AI transformation in enterprise" \
  --chunk-size 3

# With template and visual review
.venvs/demo/bin/python cookbook/90_models/anthropic/skills/powerpoint_workflow_demo/powerpoint_chunked_workflow.py \
  -p "Create a 12-slide product launch presentation for TechCorp" \
  -t my_template.pptx \
  --chunk-size 4 \
  --visual-review \
  -o final_presentation.pptx
```

### New CLI Arguments
- `--chunk-size` (int, default=3): Slides per Claude API call
- `--max-retries` (int, default=2): Retries per chunk on failure
- `--visual-passes` (int, default=3): Maximum visual inspection passes per chunk (was hardcoded to 3 before)