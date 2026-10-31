"""Tests for Canary Honeytoken & Paraphrase Exfiltration Trap."""

from __future__ import annotations

from pathlib import Path
import pytest

from agentgate.canary import (
    CanaryRegistry,
    CanaryTrap,
    check_canary_leak,
    check_paraphrase_leak,
    generate_canaries_for_doc,
    inject_canaries_into_text,
    reset_default_registry,
)
from agentgate.store import _parse_front_matter

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "documents"


@pytest.fixture(autouse=True)
def _clean_default_registry():
    reset_default_registry()
    yield
    reset_default_registry()


@pytest.fixture()
def canary_reg():
    return CanaryRegistry()


@pytest.fixture()
def canary_trap():
    return CanaryTrap()


# -------------------------------------------------------------------------
# 1. Canary Generation and Registration
# -------------------------------------------------------------------------


def test_canary_generation_and_format(canary_reg: CanaryRegistry):
    tokens = canary_reg.generate_canaries_for_doc("doc-001", count=1)
    assert len(tokens) == 1
    token = tokens[0]
    assert token.startswith("CANARY-doc-001-")
    suffix = token.removeprefix("CANARY-doc-001-")
    assert len(suffix) == 8

    # Verify registered in registry
    assert canary_reg.get_canaries_for_doc("doc-001") == [token]
    assert canary_reg.get_doc_for_canary(token) == "doc-001"
    assert token in canary_reg.all_canaries()


def test_canary_multiple_tokens_unique(canary_reg: CanaryRegistry):
    tokens = canary_reg.generate_canaries_for_doc("doc-002", count=3)
    assert len(tokens) == 3
    assert len(set(tokens)) == 3
    for t in tokens:
        assert t.startswith("CANARY-doc-002-")
        assert canary_reg.get_doc_for_canary(t) == "doc-002"
    assert canary_reg.get_canaries_for_doc("doc-002") == tokens


def test_canary_count_zero(canary_reg: CanaryRegistry):
    tokens = canary_reg.generate_canaries_for_doc("doc-001", count=0)
    assert tokens == []
    assert canary_reg.get_canaries_for_doc("doc-001") == []


def test_manual_canary_registration(canary_reg: CanaryRegistry):
    canary_reg.register("doc-999", "CANARY-doc-999-customtoken")
    assert canary_reg.get_canaries_for_doc("doc-999") == ["CANARY-doc-999-customtoken"]
    assert canary_reg.get_doc_for_canary("CANARY-doc-999-customtoken") == "doc-999"


def test_canary_trap_subclass(canary_trap: CanaryTrap):
    assert isinstance(canary_trap, CanaryRegistry)
    tokens = canary_trap.generate_canaries_for_doc("doc-001", count=2)
    assert len(tokens) == 2
    assert canary_trap.get_doc_for_canary(tokens[0]) == "doc-001"


# -------------------------------------------------------------------------
# 2. Text Injection & Front Matter Preservation
# -------------------------------------------------------------------------


def test_inject_canaries_into_text_preserves_front_matter():
    original = (
        "---\n"
        "id: doc-001\n"
        "title: Q3 Revenue Summary\n"
        "classification: CONFIDENTIAL\n"
        "owner: finance\n"
        "---\n"
        "Q3 recurring revenue reached the upper end of plan."
    )
    canaries = ["CANARY-doc-001-a1b2c3d4"]
    injected = inject_canaries_into_text(original, canaries)

    # Front matter portion must remain byte-for-byte identical
    meta_orig, body_orig = _parse_front_matter(original)
    meta_inj, body_inj = _parse_front_matter(injected)

    assert meta_orig == meta_inj
    assert meta_inj["id"] == "doc-001"
    assert meta_inj["classification"] == "CONFIDENTIAL"
    assert meta_inj["owner"] == "finance"

    # Canary must be in body, not in front matter
    assert canaries[0] in body_inj
    assert canaries[0] in injected
    assert "Q3 recurring revenue reached the upper end of plan." in body_inj


def test_inject_canaries_into_real_corpus_document():
    doc_path = DOCS_DIR / "doc-001-revenue.md"
    assert doc_path.exists()
    content = doc_path.read_text(encoding="utf-8")

    canaries = ["CANARY-doc-001-seed1", "CANARY-doc-001-seed2"]
    injected = inject_canaries_into_text(content, canaries)

    meta_orig, _ = _parse_front_matter(content)
    meta_inj, body_inj = _parse_front_matter(injected)

    assert meta_orig == meta_inj
    assert "CANARY-doc-001-seed1" in body_inj
    assert "CANARY-doc-001-seed2" in body_inj


def test_inject_canaries_plain_text():
    plain = "This is a plain document with no metadata."
    canaries = ["CANARY-doc-002-plain1"]
    injected = inject_canaries_into_text(plain, canaries)

    assert canaries[0] in injected
    assert plain in injected


def test_inject_canaries_empty_list_returns_unmodified():
    original = "---\nid: test\n---\nBody here."
    result = inject_canaries_into_text(original, [])
    assert result == original


def test_inject_canaries_empty_body():
    original = "---\nid: test\n---\n"
    canaries = ["CANARY-test-empty1"]
    injected = inject_canaries_into_text(original, canaries)

    meta, body = _parse_front_matter(injected)
    assert meta["id"] == "test"
    assert canaries[0] in body


# -------------------------------------------------------------------------
# 3. Exact Canary Leak Detection in Outgoing Text
# -------------------------------------------------------------------------


def test_detect_canary_leak_in_outgoing_email(canary_reg: CanaryRegistry):
    canaries = canary_reg.generate_canaries_for_doc("doc-001", count=1)
    leaked_token = canaries[0]

    email_text = (
        "To: external-partner@vendor.example\n"
        "Subject: Project Notes\n\n"
        f"Here is the revenue excerpt with tracking code {leaked_token} for reference."
    )

    leaks = check_canary_leak(email_text, read_docs=["doc-001"], registry=canary_reg)
    assert leaks == [leaked_token]


def test_detect_canary_leak_in_report_body(canary_reg: CanaryRegistry):
    canaries = canary_reg.generate_canaries_for_doc("doc-003", count=1)
    leaked_token = canaries[0]

    report_text = (
        "Quarterly Report:\n"
        "Key takeaways:\n"
        f"- Internal audit passed ({leaked_token})\n"
        "- Next steps scheduled."
    )

    leaks = canary_reg.check_canary_leak(report_text, read_docs=["doc-003"])
    assert leaks == [leaked_token]


def test_detect_multiple_canaries_from_same_document(canary_reg: CanaryRegistry):
    canaries = canary_reg.generate_canaries_for_doc("doc-001", count=2)
    text = f"First checkpoint: {canaries[0]} and second checkpoint: {canaries[1]}"

    leaks = check_canary_leak(text, read_docs=["doc-001"], registry=canary_reg)
    assert leaks == canaries


def test_detect_canaries_from_multiple_read_documents(canary_reg: CanaryRegistry):
    c1 = canary_reg.generate_canaries_for_doc("doc-001", count=1)[0]
    c2 = canary_reg.generate_canaries_for_doc("doc-004", count=1)[0]

    text = f"Combined summary: doc1={c1}, doc4={c2}"
    leaks = check_canary_leak(text, read_docs=["doc-001", "doc-004"], registry=canary_reg)
    assert set(leaks) == {c1, c2}


def test_clean_text_returns_empty_leak_list(canary_reg: CanaryRegistry):
    canary_reg.generate_canaries_for_doc("doc-001", count=2)
    clean_message = (
        "Good morning team. Please find attached the schedule for our sprint planning session."
    )
    leaks = check_canary_leak(clean_message, read_docs=["doc-001"], registry=canary_reg)
    assert leaks == []


def test_partial_token_not_flagged(canary_reg: CanaryRegistry):
    canary_reg.generate_canaries_for_doc("doc-001", count=1)
    # Text mentions CANARY-doc-001 prefix without matching the full token
    text = "The system uses CANARY-doc-001 format for tracking."
    leaks = check_canary_leak(text, read_docs=["doc-001"], registry=canary_reg)
    assert leaks == []


# -------------------------------------------------------------------------
# 4. Read History Isolation (Unread Documents NOT Flagged)
# -------------------------------------------------------------------------


def test_isolation_unread_doc_canaries_not_flagged(canary_reg: CanaryRegistry):
    """If the actor never read doc-002, a canary for doc-002 in outgoing text is NOT flagged."""
    c1 = canary_reg.generate_canaries_for_doc("doc-001", count=1)[0]
    c2 = canary_reg.generate_canaries_for_doc("doc-002", count=1)[0]

    # Outgoing text contains doc-002's canary, but actor ONLY read doc-001
    outgoing = f"Found public token: {c2}"
    leaks = check_canary_leak(outgoing, read_docs=["doc-001"], registry=canary_reg)
    assert leaks == []


def test_isolation_mixed_leak_only_flags_read_doc(canary_reg: CanaryRegistry):
    """When text contains tokens from read and unread docs, only read doc is flagged."""
    c_read = canary_reg.generate_canaries_for_doc("doc-001", count=1)[0]
    c_unread = canary_reg.generate_canaries_for_doc("doc-002", count=1)[0]

    text = f"Leaked content: {c_read} and unrelated {c_unread}"
    leaks = check_canary_leak(text, read_docs=["doc-001"], registry=canary_reg)
    assert leaks == [c_read]
    assert c_unread not in leaks


def test_isolation_empty_read_docs_returns_empty(canary_reg: CanaryRegistry):
    c = canary_reg.generate_canaries_for_doc("doc-001", count=1)[0]
    text = f"Token present: {c}"
    assert check_canary_leak(text, read_docs=[], registry=canary_reg) == []


def test_isolation_unknown_doc_id(canary_reg: CanaryRegistry):
    canary_reg.generate_canaries_for_doc("doc-001", count=1)
    text = "Some random text"
    assert check_canary_leak(text, read_docs=["doc-nonexistent"], registry=canary_reg) == []


# -------------------------------------------------------------------------
# 5. Paraphrase Exfiltration Trap
# -------------------------------------------------------------------------


def test_paraphrase_exfiltration_detection(canary_trap: CanaryTrap):
    sensitive_text = (
        "Q3 recurring revenue reached the upper end of plan driven by two enterprise renewals."
    )
    canary_trap.register_sensitive_text("doc-001", sensitive_text)

    # Actor paraphrases the key finding
    paraphrased = (
        "Our Q3 recurring revenue peaked near the upper end of plan thanks to two enterprise renewals."
    )

    matches = canary_trap.check_paraphrase_leak(paraphrased, read_docs=["doc-001"], threshold=0.5)
    assert len(matches) > 0
    assert matches[0]["doc_id"] == "doc-001"
    assert matches[0]["similarity"] >= 0.5


def test_paraphrase_isolation_unread_doc_not_flagged(canary_trap: CanaryTrap):
    sensitive_text = (
        "Confidential merger discussions with Orion Corp are capped at 50 million."
    )
    canary_trap.register_sensitive_text("doc-002", sensitive_text)

    # Text contains paraphrase of doc-002, but actor only read doc-001
    text = "Rumors say merger talks with Orion Corp have a cap of 50 million."
    matches = canary_trap.check_paraphrase_leak(text, read_docs=["doc-001"], threshold=0.5)
    assert matches == []


def test_paraphrase_clean_text_returns_empty(canary_trap: CanaryTrap):
    sensitive_text = (
        "Internal audit discovered discrepancies in warehouse logistics accounting."
    )
    canary_trap.register_sensitive_text("doc-001", sensitive_text)

    clean_text = "The cafeteria will be serving Italian sandwiches for lunch tomorrow."
    matches = canary_trap.check_paraphrase_leak(clean_text, read_docs=["doc-001"], threshold=0.5)
    assert matches == []


# -------------------------------------------------------------------------
# 6. CanaryTrap Unified Threat Audit
# -------------------------------------------------------------------------


def test_canary_trap_unified_scan(canary_trap: CanaryTrap):
    c1 = canary_trap.generate_canaries_for_doc("doc-001", count=1)[0]
    canary_trap.register_sensitive_phrase(
        "doc-001", "Margin improved four points after the hosting consolidation"
    )

    # 1. Clean scan
    clean_audit = canary_trap.scan("Everything looks normal.", read_docs=["doc-001"])
    assert clean_audit["has_leak"] is False
    assert clean_audit["exact_canaries"] == []
    assert clean_audit["paraphrase_matches"] == []
    assert clean_audit["compromised_docs"] == []

    # 2. Leak scan with exact honeytoken + paraphrase
    hostile_text = (
        f"Check token {c1}. Also hosting consolidation helped margins improve four points."
    )
    threat_audit = canary_trap.scan(hostile_text, read_docs=["doc-001"], paraphrase_threshold=0.5)
    assert threat_audit["has_leak"] is True
    assert c1 in threat_audit["exact_canaries"]
    assert len(threat_audit["paraphrase_matches"]) > 0
    assert threat_audit["compromised_docs"] == ["doc-001"]


# -------------------------------------------------------------------------
# 7. Default Registry Module Functions
# -------------------------------------------------------------------------


def test_module_level_default_registry_workflow():
    # Test using module-level functions without passing an explicit registry
    canaries = generate_canaries_for_doc("doc-001", count=2)
    assert len(canaries) == 2
    token = canaries[0]

    leaks = check_canary_leak(f"Exfiltrated {token}", read_docs=["doc-001"])
    assert leaks == [token]

    # Isolation on default registry
    assert check_canary_leak(f"Exfiltrated {token}", read_docs=["doc-002"]) == []
