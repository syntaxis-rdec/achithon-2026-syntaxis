"""Cryptographic Single-Use Capability Tokens for AGENTGATE.

Provides HMAC-SHA256 signed capability tokens issued by the gateway upon
authorization. Physical execution tools require and consume this single-use
token before executing any state-mutating or privileged action.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Dict, Optional, Set, Tuple

# In-memory consumed nonce set for replay protection
_CONSUMED_NONCES: Set[str] = set()

# Secret key for HMAC signing (loaded from env or stable default)
_DEFAULT_KEY = os.environ.get("AGENTGATE_SECRET_KEY", "agentgate-sovereign-capability-hmac-key-2026").encode("utf-8")


def mint_token(
    actor_id: str,
    tool: str,
    resource_id: str = "",
    recipient: str = "",
    ttl_seconds: int = 60,
    secret_key: Optional[bytes] = None,
) -> str:
    """Mints a cryptographic, single-use capability token for an authorized tool call."""
    key = secret_key or _DEFAULT_KEY
    nonce = uuid.uuid4().hex
    now = int(time.time())
    payload_dict = {
        "nonce": nonce,
        "actor_id": actor_id,
        "tool": tool,
        "resource_id": resource_id,
        "recipient": recipient,
        "iat": now,
        "exp": now + ttl_seconds,
    }

    payload_json = json.dumps(payload_dict, sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("utf-8")

    signature = hmac.new(key, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"agt.{payload_b64}.{signature}"


def verify_and_consume_token(
    token: str,
    expected_tool: str,
    expected_actor: Optional[str] = None,
    secret_key: Optional[bytes] = None,
) -> Tuple[bool, str, Optional[Dict]]:
    """Verifies and consumes a capability token, enforcing single-use and expiration.

    Returns:
        (valid: bool, status_message: str, payload: Optional[dict])
    """
    key = secret_key or _DEFAULT_KEY
    if not token or not token.startswith("agt."):
        return False, "INVALID_FORMAT: Token must begin with agt.", None

    parts = token.split(".")
    if len(parts) != 3:
        return False, "MALFORMED_TOKEN: Token must contain prefix, payload, and signature", None

    _, payload_b64, signature = parts

    # 1. Verify HMAC signature
    expected_sig = hmac.new(key, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        return False, "SIGNATURE_MISMATCH: Cryptographic signature verification failed", None

    # 2. Decode payload
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        return False, f"DECODE_ERROR: {e}", None

    # 3. Check expiration
    now = int(time.time())
    if now > payload.get("exp", 0):
        return False, "TOKEN_EXPIRED: Capability token lifetime exceeded", payload

    # 4. Check single-use nonce
    nonce = payload.get("nonce", "")
    if nonce in _CONSUMED_NONCES:
        return False, "TOKEN_REPLAYED: Capability token has already been consumed", payload

    # 5. Check tool match
    if payload.get("tool") != expected_tool:
        return False, f"TOOL_MISMATCH: Token granted for {payload.get('tool')}, attempted {expected_tool}", payload

    # 6. Check actor match if specified
    if expected_actor and payload.get("actor_id") != expected_actor:
        return False, f"ACTOR_MISMATCH: Token granted to {payload.get('actor_id')}, attempted by {expected_actor}", payload

    # Consume nonce
    _CONSUMED_NONCES.add(nonce)
    return True, "TOKEN_CONSUMED_SUCCESSFULLY", payload


def clear_consumed_tokens():
    """Utility for test suites to reset consumed nonce state."""
    _CONSUMED_NONCES.clear()

