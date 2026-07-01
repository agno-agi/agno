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

**Description:** S3MediaStorage offload against a real S3-compatible endpoint (MinIO via `AWS_ENDPOINT_URL`/`MEDIA_S3_BUCKET`). Ran with `OpenAIResponses(id="gpt-5.5")`.

**Result:** Exit 0. Three vision responses returned; 2 content-addressed objects uploaded under `agno/media/`, URL-only media skipped by default.

---

### 07_media_storage_multiturn.py

**Status:** PASS

**Description:** Multi-turn reuse with `store_media=False` + LocalMediaStorage. Turn 1 sends an image; turn 2 asks about it without re-sending. Ran with `OpenAIResponses(id="gpt-5.5")`.

**Result:** Exit 0. Turn 2 recalled the image (reference reloaded from history, URL refreshed); DB stayed far smaller than the image (raw bytes kept out of the DB).

---

