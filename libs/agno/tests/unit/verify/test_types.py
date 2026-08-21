"""Unit tests for agno.verify.types: caps, records, conveniences."""

import json

import pytest

from agno.verify import REPORT_CAP_BYTES, Verdict, Verification, VerificationAttempt, VerifiedRun
from agno.verify.types import ELISION, cap_text, encodable


def test_elision_marker_is_sixteen_bytes():
    assert len(ELISION.encode("utf-8")) == 16


def test_cap_text_keeps_head_and_tail_within_cap():
    text = "H" * 10000 + "T" * 10000
    capped = cap_text(text)
    raw = capped.encode("utf-8")
    assert len(raw) <= REPORT_CAP_BYTES
    assert capped.startswith("H")
    assert capped.endswith("T")
    assert ELISION in capped
    # Head gets one third of the budget, the tail two thirds.
    head_len = capped.index(ELISION)
    tail_len = len(capped) - head_len - len(ELISION)
    assert 2 * head_len - 8 <= tail_len <= 2 * head_len + 8


def test_cap_text_is_utf8_safe():
    text = "é" * 8000
    capped = cap_text(text)
    capped.encode("utf-8")  # would raise on a split surrogate
    assert len(capped.encode("utf-8")) <= REPORT_CAP_BYTES


def test_cap_text_leaves_short_text_alone():
    assert cap_text("short") == "short"


def test_verdict_caps_report_in_post_init():
    v = Verdict(passed=False, report="x" * 20000)
    assert len(v.report.encode("utf-8")) <= REPORT_CAP_BYTES
    assert ELISION in v.report


def test_verdict_named_returns_copy_only_when_empty():
    shared = Verdict(passed=True)
    first = shared.named("a")
    second = shared.named("b")
    assert first.name == "a" and second.name == "b"
    assert shared.name == ""  # never mutated in place
    owned = Verdict(passed=True, name="mine")
    assert owned.named("other") is owned


def test_attempt_passed_requires_verdicts():
    assert VerificationAttempt(index=0, run_id="r", status="COMPLETED").passed is False
    assert VerificationAttempt(index=0, run_id="r", status="COMPLETED", verdicts=[Verdict(True)]).passed is True


def test_to_dict_coerces_non_json_verdict_data():
    from pathlib import Path

    attempt = VerificationAttempt(
        index=0, run_id="r", status="COMPLETED", verdicts=[Verdict(False, "x", "v", {"p": Path("/tmp"), "s": {1, 2}})]
    )
    payload = json.dumps(Verification(status="pending", stop_reason=None, attempts=[attempt]).to_dict())
    assert '"/tmp"' in payload


def test_verification_to_dict_is_json_serialisable():
    attempt = VerificationAttempt(
        index=0, run_id="r0", status="COMPLETED", verdicts=[Verdict(False, "why", "v", {"k": 1})], fingerprint="f"
    )
    record = Verification(status="unverified", stop_reason="exhausted", attempts=[attempt], baseline_fingerprint="b")
    payload = json.loads(json.dumps(record.to_dict()))
    assert payload["status"] == "unverified"
    assert payload["attempts"][0]["verdicts"][0]["data"] == {"k": 1}


def test_verified_run_conveniences_delegate():
    record = Verification(status="verified", stop_reason="passed", attempts=[], baseline_fingerprint=None)
    run = VerifiedRun(output=object(), verification=record)
    assert run.status == "verified"
    assert run.passed is True
    assert run.stop_reason == "passed"
    assert run.attempts == []


@pytest.mark.parametrize(
    "text, why",
    [
        ("\udce9dossier.txt", "a filename decoded with errors='surrogateescape'"),
        ("ok \udcff\udcfe tail", "surrogates in the middle of otherwise fine text"),
    ],
)
def test_cap_text_survives_lone_surrogates(text, why):
    """A surrogate cannot be UTF-8 encoded. Left alone it raises inside the cap, and because
    Verdict.__post_init__ caps unconditionally it would take the whole run down."""
    out = cap_text(text)
    assert isinstance(out, str), why
    out.encode("utf-8")  # must not raise
    assert cap_text(out) == out, "capping twice must equal capping once"


def test_a_verdict_carrying_a_surrogate_report_does_not_raise():
    verdict = Verdict(passed=False, report="failed on \udce9dossier.txt", name="check")
    assert verdict.passed is False
    verdict.report.encode("utf-8")


def test_encodable_leaves_ordinary_text_alone():
    for text in ["", "plain", "unicode: é 中 \U0001f600", "a" * 5000]:
        assert encodable(text) == text
