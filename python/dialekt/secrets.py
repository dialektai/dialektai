"""
Secrets storage for dialekt.

Sensitive values (license keys, cloud bearer tokens, external API keys) are
kept out of ~/.dialekt/config.json and stored via the OS keychain instead:

- Linux:   GNOME Keyring (Secret Service) or KDE Wallet (via `keyring` package)
- macOS:   Keychain — but only on signed builds (see Storage model below)
- Windows: Credential Manager (future)

If no keychain backend is available we fall back to an encrypted file at
~/.dialekt/secrets.enc with a banner warning visible in the UI.

Storage model
-------------
All secrets live in a SINGLE Keychain item (service="dialekt",
account="dialekt-secrets") containing a JSON dict. One item = one ACL =
one "Always Allow" prompt for the user, ever. Per-item storage was
abandoned because macOS Keychain ACLs are bound to the item's GUID, so
each new sensitive key created its own prompt that "Always Allow"
couldn't generalise across.

macOS gate
----------
Keychain is only enabled on darwin when DIALEKT_SIGNED=1 is in the env
(Tauri sidecar spawner sets this from a compile-time check on
APPLE_SIGNING_IDENTITY). On unsigned local PyInstaller builds the
binary hash changes every rebuild → Keychain ACL trust resets → every
operation re-prompts. The encrypted-file fallback sidesteps this
without touching Keychain at all.

Public API
----------
- get_secret(name)          → str | None
- set_secret(name, value)   → None
- delete_secret(name)       → None
- migrate_from_config()     → dict with counts, run once on upgrade
- backend_info()            → dict describing which backend is live
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable

log = logging.getLogger("dialekt.secrets")

# Single keychain service+account: one item, all secrets inside as JSON.
_SERVICE = "dialekt"
_BUNDLE_ITEM = "dialekt-secrets"

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
# Without this, every get_secret() call re-imports keyring and on Linux
# does a fresh D-Bus round-trip — on macOS/Windows it could even prompt
# the user. Cache makes the cost amortised to zero after first call.
_keyring_cache: tuple[bool, str] | None = None


def _is_signed_darwin_build() -> bool:
    """True if running from a Tauri-spawned signed macOS .app.

    Tauri sets DIALEKT_SIGNED=1 when option_env!("APPLE_SIGNING_IDENTITY")
    was present at compile time (i.e. the CI release pipeline built this
    .app with a Developer ID cert). When false, the macOS Keychain code
    path is skipped because ACL trust on unsigned PyInstaller builds is
    hash-pinned and breaks on every rebuild — see module docstring.
    """
    import sys
    return sys.platform == "darwin" and os.environ.get("DIALEKT_SIGNED") == "1"


def _reset_keyring_cache() -> None:
    """Test hook: drop the cached probe result so the next call re-probes."""
    global _keyring_cache
    _keyring_cache = None


def _keyring_available() -> tuple[bool, str]:
    """Probe whether a real keyring backend is usable.

    Returns (ok, backend_name). `ok=False` means we must fall back to the
    encrypted file. Result is cached for the process lifetime.

    The probe is intentionally non-mutating: it only calls
    `keyring.get_password(_SERVICE, _BUNDLE_ITEM)`. On macOS, getting a
    non-existent or already-trusted item does NOT prompt the user — only
    the first `set_password` does. The previous round-trip probe
    (set+get+delete on a throwaway item) recreated the item every launch,
    which made "Always Allow" useless because the ACL was pinned to the
    just-deleted GUID.

    On Linux the probe runs in a 3-second daemon thread so a missing
    GNOME Keyring/KWallet daemon can't block startup.
    """
    import sys
    import threading

    global _keyring_cache
    if _keyring_cache is not None:
        return _keyring_cache

    # Unsigned macOS builds skip Keychain — see module docstring.
    if sys.platform == "darwin" and not _is_signed_darwin_build():
        log.info("keyring: unsigned macOS build — using encrypted-file fallback")
        _keyring_cache = (False, "disabled-macos-unsigned")
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
            # Non-mutating probe: get() on a non-existent item returns None
            # without prompting; on an existing item returns the value
            # silently if ACL was previously granted.
            keyring.get_password(_SERVICE, _BUNDLE_ITEM)
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


# ── Bundle storage (single Keychain item containing JSON of all secrets) ─────

def _bundle_load() -> dict:
    """Read the all-secrets JSON blob from the single Keychain item."""
    import keyring
    try:
        raw = keyring.get_password(_SERVICE, _BUNDLE_ITEM)
        if not raw:
            return {}
        return json.loads(raw)
    except Exception as e:
        log.warning("keyring bundle read failed: %s", e)
        return {}


def _bundle_save(data: dict) -> None:
    """Write the all-secrets JSON blob to the single Keychain item.

    First write on a fresh install triggers ONE "Always Allow" prompt.
    Subsequent writes on the same item reuse the granted ACL silently.
    """
    import keyring
    try:
        keyring.set_password(_SERVICE, _BUNDLE_ITEM, json.dumps(data))
    except Exception as e:
        log.error("keyring bundle write failed: %s", e)
        raise


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
        return _bundle_load().get(name)
    return _fallback_load().get(name)


def set_secret(name: str, value: str) -> None:
    ok, _ = _keyring_available()
    if ok:
        try:
            data = _bundle_load()
            data[name] = value
            _bundle_save(data)
            return
        except Exception as e:
            log.warning("keyring bundle set(%s) failed, falling back: %s", name, e)
    data = _fallback_load()
    data[name] = value
    _fallback_save(data)


def delete_secret(name: str) -> None:
    ok, _ = _keyring_available()
    if ok:
        try:
            data = _bundle_load()
            data.pop(name, None)
            _bundle_save(data)
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


def migrate_fallback_to_keyring() -> dict:
    """One-shot migration: if a secrets.enc fallback file exists AND the
    keyring backend is now usable (signed macOS build, working Linux
    keyring), move every entry into the bundle and delete the fallback.

    Triggers exactly one "Always Allow" prompt on the first signed-build
    launch (the initial set_password creates the bundle item). After that,
    all reads/writes on the same item are silent.

    Idempotent: no-op when no fallback file exists OR keyring is
    unavailable (we keep using the file then).
    """
    report = {"migrated": [], "skipped_no_file": False, "skipped_no_keyring": False}
    ok, _ = _keyring_available()
    if not ok:
        report["skipped_no_keyring"] = True
        return report
    if not _FALLBACK_FILE.exists():
        report["skipped_no_file"] = True
        return report
    file_data = _fallback_load()
    if not file_data:
        # File exists but unreadable / empty — leave it alone for triage.
        return report
    try:
        bundle = _bundle_load()
        for name, value in file_data.items():
            if value and not bundle.get(name):
                bundle[name] = value
                report["migrated"].append(name)
        _bundle_save(bundle)
        # Bundle write succeeded — safe to retire the fallback file.
        _FALLBACK_FILE.unlink()
        log.info("migrated %d secrets from fallback file → keyring bundle",
                 len(report["migrated"]))
    except Exception as e:
        log.warning("fallback→keyring migration aborted: %s", e)
    return report


def iter_known_secrets() -> Iterable[str]:
    return iter(SENSITIVE_KEYS)
