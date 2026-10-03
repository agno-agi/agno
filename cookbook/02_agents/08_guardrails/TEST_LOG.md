# Test Log -- 08_guardrails

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### custom_guardrail.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates custom guardrail. Ran successfully and produced expected output.
**Result:** Completed successfully in 18s.

---

### openai_moderation.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates openai moderation. Ran successfully and produced expected output.
**Result:** Completed successfully in 18s.

---

### output_guardrail.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates output guardrail. Ran successfully and produced expected output.
**Result:** Completed successfully in 11s.

---

### pii_detection.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates pii detection. Ran successfully and produced expected output.
**Result:** Completed successfully in 20s.

---

### prompt_injection.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates prompt injection. Ran successfully and produced expected output.
**Result:** Completed successfully in 4s.

---

## IsMalicious offline regression, 2026-10-03

### ismalicious_guard.py

**Status:** PASS (offline)

**Description:** Ran `libs/agno/tests/unit/cookbook/test_ismalicious_guard.py`
with Agno from this checkout, Python 3.12.8 and synthetic HTTP transports.
External TCP sockets were disabled; only internal Unix sockets were permitted.

**Result:** 64 tests passed, including ten native `Agent.run` call-chain cases
across `OpenAIChat` and `OpenAIResponses`. URL/content block and warn decisions
prevent the next model request; allow preserves the exact text. No live API,
model credentials or detector-accuracy claim.

### ismalicious_untrusted_content.py

**Status:** NOT RUN (live demonstration)

**Description:** The demo now uses `OpenAIResponses` with `gpt-5.6-luna` per
the cookbook conventions. Its provider's native tool boundary is covered by
the offline regression above. The standalone demonstration requires the
operator's model and IsMalicious credentials and was not invoked.

---

## IsMalicious repository-check follow-up, 2026-10-03

**Environment:** Python 3.12.8, mypy 2.1.0, Ruff 0.15.20. Repository scripts
ran in disposable copies with inherited credentials removed, a clean child
home and two Ruff threads. No source or dependency-file changes were made
for the dependency comparison. The original venv remains on SQLAlchemy 2.1.3.

**Formatting:** Full `./scripts/format.sh` passed in the disposable copy.
Seven unrelated base files needed formatting/import sorting only in that
copy; those changes are outside this cookbook PR.

**Validation, SQLAlchemy 2.1.3:** Full `./scripts/validate.sh` failed with six
core mypy errors in five files unchanged by this PR. Ruff, agnoctl mypy and
the quickstart pattern check passed. This was a local environment result,
not an upstream CI failure claim.

**Validation, SQLAlchemy 2.0.54:** Full `./scripts/validate.sh` passed in
201.2 seconds after replacing only SQLAlchemy in a separate cloned venv.
Mypy checked 1,087 Agno and 21 agnoctl files; all three Ruff targets passed;
the pattern check found zero violations in 13 quickstarts. SQLAlchemy
2.0.54 is the latest stable 2.0 release retrieved from PyPI for this check
and is permitted by the declared dependency constraints. The six local
errors disappear in this matrix; SQLAlchemy 2.1.3 remains a documented
typing compatibility limitation.

**Full unit suite:** The earlier offline `./scripts/test.sh` attempt with
the dev profile stopped at collection with 127 optional-SDK import errors
and 30 skips. It is not a passing full-suite result. The existing cookbook
regression passed 64 tests and adjacent hook regression passed 27 tests.

**Official test profile:** A dry-run of the upstream
`scripts/test_setup.sh` install recipe (`agno[tests]`, with SQLAlchemy
2.0.54 retained) resolved 530 packages. It would download 396, install
397 and remove 10, including Torch, torchvision, transformers, Docling,
ONNX Runtime, PyArrow and Chroma. The optional profile was not installed
because this is a large environment expansion. No model was downloaded,
no further full-suite run was performed, and no live service was called.
The upstream recipe also installs `brave-search --no-deps` separately.

**Review status:** Draft retained. Formatting and validation now have a
complete passing matrix, but the full unit suite remains unverified.

---
