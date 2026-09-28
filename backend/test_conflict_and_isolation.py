import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

# Enforce testing environment
os.environ["TESTING"] = "1"
os.environ["MOCK_HINDSIGHT"] = "1"

from hindsight_service import (
    resolve_safe_bank_id,
    is_sample_or_test_payload,
    retain_review_decision,
    recall_audit_memories,
    TEST_BANK_ID,
    get_default_bank_id
)
from audit import (
    parse_reviewer_decision,
    resolve_memory_conflicts,
    should_suppress_finding
)


def test_bank_isolation():
    print("\n--- TEST: Bank Isolation & Safety ---")
    real_bank = os.getenv("HINDSIGHT_BANK_ID", "urbankart-take1")
    print(f"Configured real bank: {real_bank}")

    # 1. Under test environment, default bank must always be urbankart-test
    default_b = get_default_bank_id()
    assert default_b == TEST_BANK_ID, f"Expected {TEST_BANK_ID}, got {default_b}"
    print("✓ get_default_bank_id() returned 'urbankart-test' in test mode")

    # 2. If a request explicitly attempts to pass real bank with sample or test payload:
    safe_bank = resolve_safe_bank_id(real_bank, is_test_data=True)
    assert safe_bank == TEST_BANK_ID, f"Must redirect to {TEST_BANK_ID}, got {safe_bank}"
    print(f"✓ Calling resolve_safe_bank_id with real bank '{real_bank}' and test_data redirected to '{safe_bank}'")

    # 3. Payload with test keywords detected
    assert is_sample_or_test_payload(note="unit test check") is True
    assert is_sample_or_test_payload(note="sample data review") is True
    print("✓ Test / sample payload detection confirmed")


def test_memory_conflict_resolution():
    print("\n--- TEST: Recalled Memory Conflict Resolution ---")
    memories = [
        # Earlier ruling: false alarm
        "Reviewer marked fake urgency in store_v1 as a false alarm.",
        # Later authoritative ruling: confirmed dark pattern
        "Reviewer confirmed fake urgency in store_v1 as a real dark pattern.",
        # Unrelated decision
        "Reviewer confirmed confirm-shaming in store_v1 as a real dark pattern.",
        # Another pair: earlier confirmed, later false alarm
        "Reviewer confirmed hidden fee in store_v1 as a real dark pattern (evidence: 'Convenience Fee ₹149').",
        "Reviewer marked hidden fee in store_v1 as a false alarm (evidence: 'Convenience Fee ₹149'). Note: waived for members."
    ]

    authoritative, general = resolve_memory_conflicts(memories)
    auth_dict = {f"{d['finding_type']}::{d['version']}::{d['evidence']}": d for d in authoritative}

    # 1. fake urgency in store_v1: later decision 'confirmed' should be authoritative
    fake_urgency_dec = auth_dict.get("fake urgency::store_v1::None")
    assert fake_urgency_dec is not None
    assert fake_urgency_dec["decision"] == "confirmed", (
        f"Expected most recent 'confirmed' to override 'false_alarm', got: {fake_urgency_dec['decision']}"
    )
    print("✓ Conflicting decisions on fake urgency: most recent decision ('confirmed') is authoritative")

    # 2. hidden fee with evidence: later decision 'false_alarm' should be authoritative
    hidden_fee_dec = auth_dict.get("hidden fee::store_v1::Convenience Fee ₹149")
    assert hidden_fee_dec is not None
    assert hidden_fee_dec["decision"] == "false_alarm", (
        f"Expected most recent 'false_alarm' to override 'confirmed', got: {hidden_fee_dec['decision']}"
    )
    print("✓ Conflicting decisions on hidden fee: most recent decision ('false_alarm') is authoritative")


def test_cross_version_evidence_matching():
    print("\n--- TEST: Cross-Version Evidence Matching ---")
    memories = [
        # Decision made on store_v1 regarding Diwali sale banner
        "Reviewer marked fake urgency in store_v1 as a false alarm (evidence: 'Grand Diwali Sale ends 25 Oct 2026'). Note: legitimate date.",
        # General decision made on store_v1 without specific evidence
        "Reviewer accepted pre-checked add-on in store_v1 as a legitimate design pattern."
    ]

    authoritative, _ = resolve_memory_conflicts(memories)

    # Scenario A: Auditing store_v2 with Flash Deal countdown timer (different evidence)
    # The store_v1 decision about Diwali banner MUST NOT suppress the countdown timer!
    suppress_timer_in_v2 = should_suppress_finding(
        finding_type="fake urgency",
        evidence='<div class="urgency-bar">⚡ Flash Deal reserved for you! Expires in <span id="timer">09:59</span></div>',
        current_version="store_v2",
        authoritative_decisions=authoritative
    )
    assert suppress_timer_in_v2 is False, "A decision about store_v1 Diwali banner must NOT suppress countdown timer in store_v2!"
    print("✓ store_v1 decision on Diwali banner does NOT suppress timer in store_v2 (evidence does not match)")

    # Scenario B: Auditing store_v2 with the same Diwali Sale banner (matching evidence text)
    # The decision SHOULD suppress the Diwali banner because the evidence text matches
    suppress_diwali_in_v2 = should_suppress_finding(
        finding_type="fake urgency",
        evidence='<div class="diwali-banner">🪔 Grand Diwali Sale ends 25 Oct 2026!</div>',
        current_version="store_v2",
        authoritative_decisions=authoritative
    )
    assert suppress_diwali_in_v2 is True, "Matching evidence text across versions SHOULD suppress the finding!"
    print("✓ store_v1 decision on Diwali banner DOES suppress Diwali banner in store_v2 (evidence text matches)")

    # Scenario C: A decision on store_v1 without evidence must NOT suppress store_v2 finding
    suppress_addon_in_v2 = should_suppress_finding(
        finding_type="pre-checked add-on",
        evidence='<input type="checkbox" id="priorityAddon" checked>',
        current_version="store_v2",
        authoritative_decisions=authoritative
    )
    assert suppress_addon_in_v2 is False, "A decision on store_v1 without evidence must NOT suppress findings in store_v2!"
    print("✓ Decision on store_v1 without evidence does NOT suppress finding in store_v2")


async def test_mock_hindsight_retention_and_recall():
    print("\n--- TEST: Mock Hindsight Retention and Recall ---")
    success, sentence, warning = await retain_review_decision(
        bank_id=TEST_BANK_ID,
        version="store_v1",
        finding_type="hidden fee",
        evidence="Convenience Fee ₹149",
        decision="confirmed",
        note="mock test verification"
    )
    assert success is True
    assert "Reviewer confirmed hidden fee in store_v1 as a real dark pattern" in sentence
    print(f"✓ Mock retained sentence: '{sentence}'")

    recalled, rec_warn = await recall_audit_memories(bank_id=TEST_BANK_ID)
    assert rec_warn is None
    assert any(sentence in r for r in recalled)
    print(f"✓ Mock recalled {len(recalled)} memory successfully from '{TEST_BANK_ID}'")


if __name__ == "__main__":
    test_bank_isolation()
    test_memory_conflict_resolution()
    test_cross_version_evidence_matching()
    asyncio.run(test_mock_hindsight_retention_and_recall())
    print("\n" + "=" * 60)
    print("ALL CONFLICT RESOLUTION & BANK ISOLATION TESTS PASSED!")
    print("=" * 60 + "\n")
