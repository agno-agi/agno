# Test Log: 06_storage

> Tests not yet run. Run each file and update this log.

### 01_persistent_session_storage.py

**Status:** PENDING

**Description:** Pending test coverage for `01_persistent_session_storage.py`.

---

### 02_session_summary.py

**Status:** PENDING

**Description:** Pending test coverage for `02_session_summary.py`.

---

### 03_chat_history.py

**Status:** PENDING

**Description:** Pending test coverage for `03_chat_history.py`.

---

### 05_media_storage_local.py

**Status:** PASS

**Description:** LocalMediaStorage offload. Sends image bytes and a URL-only image, then repeats with `persist_remote_urls=True`. Ran with `OpenAIResponses(id="gpt-5.5")`.

**Result:** Exit 0. Content media offloaded to `./tmp/media_storage` (2 files), URL-only media correctly skipped by default, and downloaded+stored when `persist_remote_urls=True`.

---

### 06_media_storage_s3.py

**Status:** PASS

**Description:** S3MediaStorage offload against a real AWS S3 bucket (`MEDIA_S3_BUCKET`, no `AWS_ENDPOINT_URL`). Ran with `OpenAIResponses(id="gpt-5.5")`.

**Result:** Exit 0. Three vision responses returned; 2 content-addressed objects uploaded under `agno/media/` (65129 bytes each, matching the source hash), URL-only media skipped by default. The persisted run holds a `media_reference`, not base64.

---

### 07_media_storage_multiturn.py

**Status:** PASS

**Description:** Multi-turn reuse with S3MediaStorage against a real AWS bucket (`MEDIA_S3_BUCKET`). Turn 1 sends an image; turn 2 asks about it without re-attaching it. Ran with `OpenAIResponses(id="gpt-5.5", store=False)` so history stays client-side.

**Result:** Exit 0, both turns answered about the same image, no offload-failure warning. Turn 1 uploaded one object (113255 bytes) under the session-scoped key `multiturn-session-<media_id>-<hash>.jpg` and sent 151008 base64 chars to the model. Instrumenting the outbound request shows turn 2 carries one `input_image` holding a freshly presigned S3 URL — 0 base64 chars and 0 `download()` calls, so the model reads the object from S3 directly. The run row stays at 2897 bytes with a `media_reference` and no base64.

---

### 08_media_storage_gcs.py

**Status:** PASS

**Description:** GCSMediaStorage offload with application-default credentials.

**Result:** Objects uploaded under `agno/media/`; the persisted run holds a `media_reference` with backend `gcs`. ADC cannot sign URLs, so the reference stores no URL and AgentOS streams the bytes instead.

---

### 09_media_storage_delete.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Two sessions each offload the same image to a real S3 bucket (`MEDIA_S3_BUCKET`, prefix `agno/media_delete/`). One is deleted without the flag, the other with `delete_media=True`. Ran with `OpenAIResponses(id="gpt-5.5")`.

**Result:** Exit 0. Two objects in S3 after the runs; deleting the first session without the flag left both; deleting the second with `delete_media=True` swept only its own object, leaving one — the deliberate orphan from the un-flagged delete, which the example prints by key.

---

### 10_media_storage_workflow.py

**Status:** PASS

**Test mode:** LIVE

**Description:** A workflow offloads both the image passed to `workflow.run(images=...)` and the image a step's agent produced, to a real S3 bucket (`MEDIA_S3_BUCKET`). Ran with `OpenAIResponses(id="gpt-5.5")`.

**Result:** Exit 0. The run row carried a MediaReference with `inline bytes: None`; the object was 65129 bytes in the bucket.

---

### 11_media_storage_file_generation.py

**Status:** PASS

**Test mode:** LIVE

**Description:** `FileGenerationTools` generates a CSV, media storage offloads it to a real S3 bucket, and the example reads it back with `get_content_bytes(storage=...)` and mints a link with `get_url(storage=...)`. Ran with `OpenAIResponses(id="gpt-5.5")`.

**Result:** Exit 0. The row kept only a reference (`inline bytes: None`); the read-back returned 93 bytes with the correct first line, and `get_url` returned a real presigned S3 URL.

---
