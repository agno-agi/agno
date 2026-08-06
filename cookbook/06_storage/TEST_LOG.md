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

**Description:** Multi-turn reuse with LocalMediaStorage. Turn 1 sends an image; turn 2 asks about it without re-sending. Ran with `OpenAIResponses(id="gpt-5.5", store=False)` so history stays client-side.

**Result:** Exit 0, both turns answered about the same image. Instrumenting the outbound request shows turn 2 carries one `input_image` (~151 KB) re-read from storage, while the run row stays at 3002 bytes with only a `media_reference`.

---

### 08_media_storage_gcs.py

**Status:** PASS

**Description:** GCSMediaStorage offload with application-default credentials.

**Result:** Objects uploaded under `agno/media/`; the persisted run holds a `media_reference` with backend `gcs`. ADC cannot sign URLs, so the reference stores no URL and AgentOS streams the bytes instead.

---
