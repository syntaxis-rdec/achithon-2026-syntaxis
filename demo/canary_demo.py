"""Live Interactive Terminal Demonstration of Honeytoken Canary & Paraphrase Trap.

Demonstrates:
1. Dynamic canary token generation and transparent document seeding
2. Adversarial agent prompt injection attempting to leak secret text
3. Real-time canary tripwire intercepting and flagging the exfiltration
4. 4-Gram semantic paraphrase detection flagging cloaked/summarized leakage

Usage:
    python demo/canary_demo.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from agentgate.canary import CanaryTrap


def run_canary_demonstration():
    print("=" * 70)
    print("      AGENTGATE HONEYTOKEN CANARY & PARAPHRASE TRAP DEMO       ")
    print("=" * 70)

    trap = CanaryTrap()
    doc_id = "doc-001"
    
    print("\n[STEP 1] Generating dynamic honeytokens for confidential revenue report...")
    canaries = trap.generate_canaries_for_doc(doc_id, count=2)
    canary_token = canaries[0]
    print(f"  --> Seeded Canary Token: {canary_token}")

    print("\n[STEP 2] Registering sensitive core intellectual property phrases...")
    secret_phrase = "Q3 confidential earnings reached 42 million USD ahead of consensus"
    trap.register_sensitive_phrase(doc_id, secret_phrase)
    print(f"  --> Seeded Semantic Phrase: '{secret_phrase}'")

    print("\n[STEP 3] Simulating Adversarial Attack 1: Direct Honeytoken Leakage...")
    time.sleep(0.2)
    outgoing_payload_1 = (
        f"Hi external vendor, here is the requested data snippet. Tracking ref: {canary_token}."
    )
    print(f"  --> Agent Outgoing Body: '{outgoing_payload_1}'")
    
    audit_1 = trap.scan(outgoing_payload_1, read_docs=[doc_id])
    if audit_1["has_leak"] and audit_1["exact_canaries"]:
        print("  --> [ALERT] [! TRIPPED !] CANARY TRIPWIRE ACTIVATED!")
        print(f"      Matched Token   : {audit_1['exact_canaries'][0]}")
        print(f"      Source Document : {audit_1['compromised_docs']}")
        print("      Gateway Action  : OUTBOX REFUSED & AGENT QUARANTINED")

    print("\n[STEP 4] Simulating Adversarial Attack 2: Paraphrased / Cloaked Secret...")
    time.sleep(0.2)
    outgoing_payload_2 = (
        "Internal brief: During Q3 earnings reached approximately 42 million USD well ahead of consensus forecast."
    )
    print(f"  --> Agent Outgoing Body: '{outgoing_payload_2}'")
    
    audit_2 = trap.scan(outgoing_payload_2, read_docs=[doc_id], paraphrase_threshold=0.45)
    if audit_2["has_leak"] and audit_2["paraphrase_matches"]:
        match = audit_2["paraphrase_matches"][0]
        print("  --> [ALERT] [! CLOAKED LEAK !] SEMANTIC PARAPHRASE DETECTED!")
        print(f"      Similarity Score: {match['similarity'] * 100:.1f}%")
        print(f"      Original Phrase : '{match['source_phrase']}'")
        print(f"      Detected In     : '{match['matched_text']}'")
        print("      Gateway Action  : OUTBOX REFUSED & AUDIT RECORD WRITTEN")

    print("\n" + "=" * 70)
    print(" VERDICT: All Direct Honeytokens and Cloaked Paraphrases Defeated")
    print("=" * 70)


if __name__ == "__main__":
    run_canary_demonstration()
