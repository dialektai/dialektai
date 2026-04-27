"""
Secrets storage for dialekt.

Sensitive values (license keys, cloud bearer tokens, external API keys) are
kept out of ~/.dialekt/config.json and stored via the OS keychain instead:

- Linux:   GNOME Keyring (Secret Service) or KDE Wallet (via `keyring` package)
- macOS:   Keychain (future)
- Windows: Credential Manager (future)

If no keychain backend is available AND the user has opted out of setting a
master password, we fall back to an encrypted file at
~/.dialekt/secrets.enc with a banner warning visible in the UI. This
matches the TASK spec's "flexibility" clause — some Linux setups genuinely
have no keychain, and refusing to run would be worse UX for pilots.

Public API
----------
- get_secret(name)          → str | None
- set_secret(name, value)   → None
- delete_secret(name)       → None
- migrate_from_config()     → dict with counts, run once on upgrade
- backend_info()            → dict describing which backend is live

All keys live under service="dialekt", account=<name>.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable

log = logging.getLogger("dialekt.secrets")

# Single keychain service name; keys are accounts within it.
_SERVICE = "dialekt"

# Names that must NEVER land in plaintext ~/.dialekt/config.json.
# migrate_from_config() consumes this list on upgrade.
#
# Per-provider credential keys (provider_<id>_<field>) are appended at
# import time from the LLM catalog so the migration loop scrubs them
# alongside the static keys. Importing the catalog here is safe because
# catalog.py has no runtime dependencies on dialekt.* — it's pure data.
_STATIC_KEYS: tuple[str, ...] = (
    "license_key",
    "cloud_bearer_token",
    "cloud_api_key",         # legacy, superseded by bearer_token
)

try:
    from dialekt.llm.catalog import all_provider_secret_keys
    _PROVIDER_KEYS: tuple[str, ...] = all_provider_secret_keys()
except Exception:
    # Catalog import failure must not brick the keychain layer — fall back
    # to static keys only. A broken catalog is a UI bug, not a security bug.
    _PROVIDER_KEYS = ()

SENSITIVE_KEYS: tuple[str, ...] = _STATIC_KEYS + _PROVIDER_KEYS

_CONFIG_DIR = Path.home() / ".dialekt"
_CONFIG_FILE = _CONFIG_DIR / "config.json"
_FALLBACK_FILE = _CONFIG_DIR / "secrets.enc"


# ── Backend probing ───────────────────────────────────────────────────────────

# Process-level cache: probe once per process lifetime.
# Without this, every get_secret() call re-probes the keychain (3 round-trips
# each), causing 30+ × 3 = 90+ D-Bus ops during startup that block the async
# lifespan for several seconds — and on macOS/Windows the probe can show a
# system auth dialog that hangs the sidecar subprocess indefinitely.
_keyring_cache: tuple[bool, str] | None = None


def _keyring_available() -> tuple[bool, str]:
    """Probe whether a real keyring backend is usable.

    Returns (ok, backend_name). `ok=False` means we must fall back to the
    encrypted file (or plaintext, if the user disables encryption).

    Result is cached for the process lifetime — call once, pay once.
    The probe runs in a daemon thread with a 3-second timeout so a locked
    or missing keychain daemon (D-Bus on Linux, Keychain on macOS, Credential
    Manager on Windows) can never block the FastAPI startup path.
    """
    import threading

    global _keyring_cache
    if _keyring_cache is not None:
        return _keyring_cache

    result: list = [False, "timeout"]

    def _probe() -> None:
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring
            kr = keyring.get_keyring()
            if isinstance(kr, FailKeyring):
                result[0], result[1] = False, "fail"
                return
            name = type(kr).__module__.split(".")[-1] + "." + type(kr).__name__
            # Chainer wraps real backends — drill down for the first working one
            if hasattr(kr, "backends"):
                for inner in kr.backends:
                    if not isinstance(inner, FailKeyring):
                        name = type(inner).__module__.split(".")[-1] + "." + type(inner).__name__
                        break
            # Round-trip test on a throwaway key — catches the common
            # "D-Bus secret service daemon not running" case at runtime
            probe_key = "__probe__"
            keyring.set_password(_SERVICE, probe_key, "ok")
            assert keyring.get_password(_SERVICE, probe_key) == "ok"
            keyring.delete_password(_SERVICE, probe_key)
            result[0], result[1] = True, name
        except Exception as e:
            log.warning("keyring backend not usable: %s", e)
            result[0], result[1] = False, f"error: {e}"

    t = threading.Thread(target=_probe, daemon=True)
    t.start()
    t.join(timeout=3.0)
    if t.is_alive():
        log.warning("keyring probe timed out after 3s — falling back to encrypted file")

    _keyring_cache = (result[0], result[1])
    return _keyring_cache


# ── File fallback (XOR-with-scrypt encrypted) ─────────────────────────────────
#
# The fallback uses the machine's hostname + user as the key-derivation salt.
# This is NOT cryptographically strong against a local attacker — the whole
# point is to keep secrets out of casually-readable text and out of `ps` /
# backups / git accidents. A real threat model (stolen disk) requires a user
# master password; we surface a UI banner when we end up here.

def _fallback_cipher_key() -> bytes:
    import hashlib
    salt = (os.uname().nodename + "|" + os.environ.get("USER", "")).encode()
    return hashlib.scrypt(b"dialekt-secrets", salt=salt, n=2**14, r=8, p=1, dklen=32)


def _fallback_load() -> dict:
    if not _FALLBACK_FILE.exists():
        return {}
    try:
        import base64
        key = _fallback_cipher_key()
        blob = base64.b64decode(_FALLBACK_FILE.read_bytes())
        out = bytearray(len(blob))
        for i, b in enumerate(blob):
            out[i] = b ^ key[i % len(key)]
        return json.loads(bytes(out))
    except Exception as e:
        log.warning("fallback secrets store unreadable: %s", e)
        return {}


def _fallback_save(data: dict) -> None:
    import base64
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    key = _fallback_cipher_key()
    payload = json.dumps(data).encode()
    out = bytearray(len(payload))
    for i, b in enumerate(payload):
        out[i] = b ^ key[i % len(key)]
    _FALLBACK_FILE.write_bytes(base64.b64encode(bytes(out)))
    os.chmod(_FALLBACK_FILE, 0o600)


# ── Public API ────────────────────────────────────────────────────────────────

def backend_info() -> dict:
    """Return which backend is live, for UI display and logging."""
    ok, name = _keyring_available()
    if ok:
        return {"kind": "keyring", "name": name, "path": None, "secure": True}
    return {
        "kind": "fallback",
        "name": "xor-scrypt",
        "path": str(_FALLBACK_FILE),
        "secure": False,
    }


def get_secret(name: str) -> str | None:
    ok, _ = _keyring_available()
    if ok:
        import keyring
        try:
            return keyring.get_password(_SERVICE, name)
        except Exception as e:
            log.warning("keyring get(%s) failed: %s", name, e)
    return _fallback_load().get(name)


def set_secret(name: str, value: str) -> None:
    ok, _ = _keyring_available()
    if ok:
        import keyring
        try:
            keyring.set_password(_SERVICE, name, value or "")
            return
        except Exception as e:
            log.warning("keyring set(%s) failed, falling back: %s", name, e)
    data = _fallback_load()
    data[name] = value
    _fallback_save(data)


def delete_secret(name: str) -> None:
    ok, _ = _keyring_available()
    if ok:
        import keyring
        try:
            keyring.delete_password(_SERVICE, name)
            return
        except Exception:
            pass
    data = _fallback_load()
    data.pop(name, None)
    _fallback_save(data)


def migrate_from_config(config_path: Path | None = None) -> dict:
    """On upgrade, move any plaintext sensitive fields out of config.json
    and into the keychain (or fallback). Returns migration report.

    Idempotent — safe to call every app launch.
    """
    path = Path(config_path or _CONFIG_FILE)
    report = {"migrated": [], "skipped": [], "config_path": str(path)}
    if not path.exists():
        return report
    try:
        cfg = json.loads(path.read_text())
    except Exception as e:
        log.error("cannot read %s for migration: %s", path, e)
        return report
    if not isinstance(cfg, dict):
        return report
    changed = False
    for name in SENSITIVE_KEYS:
        if name in cfg and cfg[name]:
            existing = get_secret(name)
            if existing and existing == cfg[name]:
                # Already in keychain and matches — delete plaintext copy only.
                cfg.pop(name, None)
                report["skipped"].append(name)
                changed = True
                continue
            set_secret(name, cfg[name])
            cfg.pop(name, None)
            report["migrated"].append(name)
            changed = True
    if changed:
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        log.info("migrated secrets: %s (moved out of %s)", report["migrated"], path)
    return report


def iter_known_secrets() -> Iterable[str]:
    return iter(SENSITIVE_KEYS)
