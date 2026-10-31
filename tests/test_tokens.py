"""Unit tests for AGENTGATE cryptographic single-use capability tokens."""

from __future__ import annotations

import time
import pytest

from agentgate.tokens import (
    clear_consumed_tokens,
    mint_token,
    verify_and_consume_token,
)


@pytest.fixture(autouse=True)
def reset_tokens():
    clear_consumed_tokens()


def test_valid_token_mints_and_consumes():
    token = mint_token(actor_id="analyst", tool="read_document", resource_id="doc-001")
    assert token.startswith("agt.")

    valid, msg, payload = verify_and_consume_token(
        token=token,
        expected_tool="read_document",
        expected_actor="analyst",
    )
    assert valid is True
    assert msg == "TOKEN_CONSUMED_SUCCESSFULLY"
    assert payload["actor_id"] == "analyst"
    assert payload["tool"] == "read_document"


def test_token_replay_is_strictly_rejected():
    token = mint_token(actor_id="analyst", tool="read_document", resource_id="doc-001")

    # First consumption succeeds
    valid, _, _ = verify_and_consume_token(token, "read_document", "analyst")
    assert valid is True

    # Second consumption MUST FAIL (single-use invariant)
    replayed, msg, _ = verify_and_consume_token(token, "read_document", "analyst")
    assert replayed is False
    assert "TOKEN_REPLAYED" in msg


def test_tampered_signature_is_rejected():
    token = mint_token(actor_id="analyst", tool="read_document", resource_id="doc-001")
    parts = token.split(".")
    # Tamper with the signature hex
    tampered_sig = parts[2][:-4] + "dead"
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

    valid, msg, _ = verify_and_consume_token(tampered_token, "read_document", "analyst")
    assert valid is False
    assert "SIGNATURE_MISMATCH" in msg


def test_expired_token_is_rejected():
    # Mint token with -1s TTL
    token = mint_token(actor_id="analyst", tool="read_document", ttl_seconds=-1)

    valid, msg, _ = verify_and_consume_token(token, "read_document", "analyst")
    assert valid is False
    assert "TOKEN_EXPIRED" in msg


def test_tool_mismatch_is_rejected():
    token = mint_token(actor_id="analyst", tool="read_document", resource_id="doc-001")

    # Attempting to use a read token for save_report
    valid, msg, _ = verify_and_consume_token(token, "save_report", "analyst")
    assert valid is False
    assert "TOOL_MISMATCH" in msg

