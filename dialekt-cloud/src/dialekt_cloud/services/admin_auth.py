"""
Admin auth primitives — argon2id password hashing, TOTP, AES-GCM secret
encryption, backup codes, challenge tokens.

Replaces the legacy single-static-key model with email + password + TOTP
per admin_2fa_DESIGN.md. The static `DIALEKT_ADMIN_KEY` env var stays
defined as a header-only break-glass; it does NOT mint cookies.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time as _time
from dataclasses import dataclass
from io import BytesIO

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings


# ── Password hashing (argon2id) ─────────────────────────────────────────────
# OWASP 2024 baseline params. argon2id is the modern default.
_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)


def hash_password(plain: str) -> str:
    """Returns the full PHC string (algo + params + salt + hash) ready to
    drop into admins.password_hash."""
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _ph.verify(hashed, plain)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


# ── TOTP secret encryption at rest (AES-256-GCM) ────────────────────────────
# Mentor approval: AES-GCM with 32-byte key from DIALEKT_ADMIN_TOTP_KEY env.

def _totp_aead() -> AESGCM:
    raw = base64.b64decode(settings.DIALEKT_ADMIN_TOTP_KEY)
    if len(raw) != 32:
        raise RuntimeError(
            "DIALEKT_ADMIN_TOTP_KEY must decode to exactly 32 bytes "
            f"(got {len(raw)}). Generate with: "
            "python -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())'"
        )
    return AESGCM(raw)


def encrypt_totp_secret(secret_b32: str) -> str:
    """Encrypt + b64-encode the base32 TOTP secret for storage."""
    aead = _totp_aead()
    nonce = os.urandom(12)
    ct = aead.encrypt(nonce, secret_b32.encode("ascii"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_totp_secret(stored: str) -> str:
    aead = _totp_aead()
    blob = base64.b64decode(stored)
    nonce, ct = blob[:12], blob[12:]
    return aead.decrypt(nonce, ct, None).decode("ascii")


# ── TOTP code generation + verification ────────────────────────────────────

def new_totp_secret() -> str:
    """Returns a fresh base32 secret usable in otpauth URIs."""
    return pyotp.random_base32()


def provisioning_uri(secret_b32: str, email: str) -> str:
    """Format: otpauth://totp/dias.now:dias%40dias.now?secret=...&issuer=dias.now"""
    return pyotp.totp.TOTP(secret_b32).provisioning_uri(name=email, issuer_name="dias.now")


def verify_totp(secret_b32: str, code: str, valid_window: int = 1) -> bool:
    """30s period · ±1 step skew tolerance (= ~90s effective window)."""
    if not code or not code.strip().isdigit():
        return False
    return pyotp.totp.TOTP(secret_b32).verify(code.strip(), valid_window=valid_window)


def qr_svg(secret_b32: str, email: str) -> str:
    """Inline SVG QR code (no external image fetch). Returns the SVG string."""
    import qrcode
    from qrcode.image.svg import SvgPathImage
    img = qrcode.make(provisioning_uri(secret_b32, email), image_factory=SvgPathImage)
    buf = BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


# ── Backup codes ────────────────────────────────────────────────────────────
# 10 codes, 8 chars from [A-HJ-NP-Z2-9] (no ambiguous 0/O/1/I/L). Hashed with
# argon2id at rest. Plaintext shown ONCE at generation time.
_BACKUP_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_backup_codes(n: int = 10, length: int = 8) -> tuple[list[str], list[str]]:
    """Returns (plaintext_codes, hashed_codes). Caller stores hashed list,
    shows plaintext list to the user exactly once."""
    plaintext = ["".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(length)) for _ in range(n)]
    hashed = [_ph.hash(c) for c in plaintext]
    return plaintext, hashed


def consume_backup_code(code: str, hashed_codes: list[str]) -> tuple[bool, list[str]]:
    """Returns (matched, remaining_hashes). On match, the consumed code is
    removed from the returned list — caller persists the new list to invalidate."""
    code = (code or "").strip().upper().replace(" ", "")
    if not code:
        return False, hashed_codes
    out = []
    matched = False
    for h in hashed_codes:
        if not matched:
            try:
                _ph.verify(h, code)
                matched = True
                continue  # drop this hash
            except (VerifyMismatchError, InvalidHashError):
                pass
        out.append(h)
    return matched, out


# ── Challenge token (between password success and TOTP step) ───────────────
# Short-lived HMAC-signed JWT-shape: payload + signature. Carries
# {admin_id, stage, exp}. Cannot be reused across stages.

CHALLENGE_TTL_SECONDS = 300  # 5 minutes


@dataclass(frozen=True)
class ChallengePayload:
    admin_id: str
    stage: str   # 'totp_challenge' | 'enroll_totp'
    exp: int


def issue_challenge(admin_id: str, stage: str) -> str:
    payload = {"admin_id": admin_id, "stage": stage, "exp": int(_time.time()) + CHALLENGE_TTL_SECONDS}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = _hmac_sign(body)
    return f"{body}.{sig}"


def verify_challenge(token: str, expected_stage: str) -> ChallengePayload | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _hmac_sign(body)):
        return None
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        return None
    if payload.get("stage") != expected_stage:
        return None
    if int(payload.get("exp", 0)) < int(_time.time()):
        return None
    return ChallengePayload(
        admin_id=payload["admin_id"],
        stage=payload["stage"],
        exp=int(payload["exp"]),
    )


def _hmac_sign(body: str) -> str:
    sig = hmac.new(
        settings.JWT_SECRET.encode() + b"_admin_challenge",
        body.encode(),
        "sha256",
    ).digest()
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
