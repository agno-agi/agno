# REVIEW_LOG — google/gemini

## v2.5 Review — 2026-02-11

### Framework Issues

#### 1. gemini.py — No credential fail-fast
`Gemini.__post_init__()` does not validate that `GOOGLE_API_KEY` or `GEMINI_API_KEY` is set. Errors only surface at first API call. Should fail-fast with a clear error at construction.

#### 2. gemini.py — File upload returns None on error
When `upload_file()` or `get_file()` fails (403 PERMISSION_DENIED, file not found), the method returns `None` without raising. Callers like `audio_input_file_upload.py` then pass `None` to `Audio(content=None)`, causing a confusing pydantic validation error instead of a clear "upload failed" error. Affects: audio_input_file_upload, video_input_file_upload.

#### 3. base.py:257 — kwargs mutation in invoke() (shared with anthropic)
See anthropic REVIEW_LOG for details.

---

### Cookbook Quality Notes

#### v2.5 Breaking: agent.run_response removed
`imagen_tool.py` and `imagen_tool_advanced.py` use `agent.run_response` attribute which was removed in v2.5. Should use `agent.run()` and capture the returned `RunOutput` instead.

#### v2.5 Breaking: PDFUrlKnowledgeBase removed
`storage_and_memory.py` imports `PDFUrlKnowledgeBase` from `agno.knowledge`, which no longer exists. Should use `PDFKnowledgeBase` with URL source or `URLKnowledgeBase`.

#### Old SDK import
`image_input_file_upload.py` imports from `google.generativeai` (old SDK) instead of `google.genai` (current SDK). Needs migration to new import paths.

#### Missing local files
`file_search_basic.py` and `file_search_advanced.py` reference local document files (`documents/sample.txt`, `documents/technical_manual.txt`) that don't exist. Cookbooks should either create these files inline or download them.

`pdf_input_file_upload.py` references `ThaiRecipes.pdf` which doesn't exist locally. Other PDF cookbooks (pdf_input_local, pdf_input_url) download the file first.

#### Wrong provider in google/ section
`imagen_tool.py` instantiates `OpenAIChat` (not Gemini) for image generation alongside Gemini — this is confusing placement in the google/ cookbook directory.

#### Top-level execution
Multiple cookbooks execute API calls outside `if __name__ == "__main__":` guard. Affects: knowledge.py, storage_and_memory.py, and others.

---

### v2.5 Compatibility

**Status:** 3 breaking changes found.

| File | Issue | v2.5 Change |
|------|-------|-------------|
| imagen_tool.py | `agent.run_response` | Attribute removed |
| imagen_tool_advanced.py | `agent.run_response` | Attribute removed |
| storage_and_memory.py | `PDFUrlKnowledgeBase` | Class removed |

---

### Fixes Applied

None — v2.5 breaks logged but not fixed (require design decisions on replacement patterns).

---

### Summary
- **43 files tested:** 34 PASS, 9 FAIL
- **Framework issues:** 2 (credential fail-fast, file upload None handling)
- **Cookbook quality issues:** 5 (old SDK, missing files, wrong provider, top-level execution, removed API usage)
- **v2.5 compat breaks:** 3 files (run_response x2, PDFUrlKnowledgeBase x1)
