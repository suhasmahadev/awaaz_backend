"""
Cryptographic identity and audit utilities — AWAAZ-PROOF.
ANTIGRAVITY: original had insecure ANON_SALT default and was missing
generate_audit_signature / verify_audit_signature entirely.
"""
import hashlib
import hmac
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── ANON_SALT ───────────────────────────────────────────────────────────────────
# ANTIGRAVITY: raise KeyError if missing — no insecure fallback in production paths.
# Set ANON_SALT in .env before starting the server.
_ANON_SALT: Optional[str] = os.environ.get("ANON_SALT")
if not _ANON_SALT:
    # Log loudly but don't crash at import time — crash at call time instead.
    # This allows the server to start and show the error in context.
    logger.critical(
        "ANON_SALT is not set in environment. "
        "generate_anon_id() will raise until ANON_SALT is configured."
    )

# ── ENCLAVE_KEY ─────────────────────────────────────────────────────────────────
_ENCLAVE_KEY: Optional[str] = os.environ.get("ENCLAVE_KEY")
if not _ENCLAVE_KEY:
    logger.critical(
        "ENCLAVE_KEY is not set in environment. "
        "generate_audit_signature() will raise until ENCLAVE_KEY is configured."
    )


def generate_anon_id(fingerprint: str) -> str:
    """
    Maps raw device fingerprint to a deterministic, irreversible anon_id.

    The raw fingerprint is NEVER stored, NEVER logged, NEVER returned in responses.
    Only the SHA-256 hash (salted) is stored in the anonymous_reporters table.

    Args:
        fingerprint: Raw device fingerprint (browser ID, hardware ID, etc.)
                     Must be non-empty. Max 500 chars enforced here.

    Returns:
        64-character lowercase hex string (SHA-256 output).

    Raises:
        ValueError: If fingerprint is empty or exceeds 500 chars.
        RuntimeError: If ANON_SALT is not configured in environment.
    """
    # ANTIGRAVITY: explicit validation — never trust caller to validate
    if not fingerprint or not fingerprint.strip():
        raise ValueError("fingerprint must be a non-empty string")
    if len(fingerprint) > 500:
        raise ValueError("fingerprint must not exceed 500 characters")

    salt = _ANON_SALT
    if not salt:
        raise RuntimeError(
            "ANON_SALT is not set. Configure it in .env before using /auth/anon. "
            "Example: ANON_SALT=your-secret-salt-here"
        )

    raw = f"{fingerprint}{salt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_evidence_payload(payload: bytes) -> str:
    """
    SHA-256 hash of raw evidence bytes (photo/video/sensor binary).

    ANTIGRAVITY: confirmed takes `bytes`, returns lowercase hex string.
    Hash is computed BEFORE file is stored — ensures hash matches what was received.

    Args:
        payload: Raw bytes of the evidence file.

    Returns:
        64-character lowercase hex string.

    Raises:
        TypeError: If payload is not bytes.
    """
    if not isinstance(payload, bytes):
        raise TypeError(f"payload must be bytes, got {type(payload).__name__}")
    return hashlib.sha256(payload).hexdigest()


def generate_audit_signature(payload: dict, key: Optional[str] = None) -> str:
    """
    HMAC-SHA256 signature over a canonically serialised payload dict.

    ANTIGRAVITY: was missing entirely from original hashing.py.
    Uses json.dumps with sort_keys=True for canonical form.

    Args:
        payload: Dict to sign. Must be JSON-serialisable.
        key:     HMAC key. Defaults to ENCLAVE_KEY from environment.

    Returns:
        64-character lowercase hex HMAC-SHA256 digest.

    Raises:
        RuntimeError: If key is not set.
        ValueError: If payload is empty.
    """
    signing_key = key or _ENCLAVE_KEY
    if not signing_key:
        raise RuntimeError(
            "ENCLAVE_KEY is not set. Configure it in .env before generating audit signatures."
        )
    if not payload:
        raise ValueError("payload must be non-empty to sign")

    payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        signing_key.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_audit_signature(payload: dict, signature: str, key: Optional[str] = None) -> bool:
    """
    Constant-time verification of audit log entry signature.

    ANTIGRAVITY: was missing entirely from original hashing.py.
    Uses hmac.compare_digest() to prevent timing attacks.

    Args:
        payload:   Dict that was signed (must match exactly what was signed).
        signature: Stored hex HMAC-SHA256 digest.
        key:       HMAC key. Defaults to ENCLAVE_KEY from environment.

    Returns:
        True if signature matches; False if tampered, wrong key, or empty.
    """
    if not payload or not signature:
        return False

    signing_key = key or _ENCLAVE_KEY
    if not signing_key:
        logger.warning("verify_audit_signature called without ENCLAVE_KEY — returning False")
        return False

    try:
        expected = generate_audit_signature(payload, signing_key)
        return hmac.compare_digest(expected, signature)
    except (ValueError, TypeError) as exc:
        logger.warning("verify_audit_signature failed: %s", exc)
        return False
