# TEST_LOG.md - 91 Tools Models

**Test Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`

---

### azure_openai_tools.py

**Status:** SKIP

**Description:** Azure OpenAI Tools with DALL-E image generation (standard OpenAI + Azure, full Azure).

**Result:** Skipped — requires AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_IMAGE_DEPLOYMENT.

---

### gemini_image_generation.py

**Status:** FAIL

**Description:** GeminiTools image generation with Gemini imagen model.

**Result:** imagen-3.0-generate-002 not found for API version v1beta. Gemini API-side model availability issue, not a v2.5 compat issue. Framework code executed correctly.

---

### gemini_video_generation.py

**Status:** SKIP

**Description:** GeminiTools video generation with Vertex AI.

**Result:** Skipped — requires GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION for Vertex AI.

---

### morph.py

**Status:** SKIP

**Description:** Morph Fast Apply for file creation and editing.

**Result:** Skipped — requires Morph API key for morph-v3-large model.

---

### nebius_tools.py

**Status:** PASS

**Description:** NebiusTools text-to-image generation with 3 models (flux-schnell, flux-dev, sdxl).

**Result:** Examples 1-2 PASS (flux-schnell, flux-dev images generated). Example 3 partial (stability-ai/sdxl model not found on Nebius). Framework works correctly.

---

### openai_tools.py

**Status:** PASS

**Description:** OpenAITools for transcription (gpt-4o-transcribe) and image generation (gpt-image-1).

**Result:** Audio transcription completed. Image generated and saved. Both tools working.

---

## Summary

| PASS | FAIL | SKIP | Total |
|------|------|------|-------|
| 2    | 1    | 3    | 6     |
