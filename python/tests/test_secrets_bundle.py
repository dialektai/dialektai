"""Unit tests for the single-Keychain-item bundle storage in dialekt.secrets.

Mocks the `keyring` package so tests never touch the real OS keychain. Covers:

- Signed-build gate: DIALEKT_SIGNED env + darwin platform check
- Lazy probe: get_password only, never set/delete
- Bundle round-trip: get/set/delete operate on a single JSON item
- Fallback → bundle migration: secrets.enc gets emptied into Keychain
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _fresh_secrets_mod(monkeypatch, *, signed: bool = False):
    """Reload dialekt.secrets with a mocked keyring backend and clean cache."""
    from dialekt import secrets as secrets_mod
    secrets_mod._reset_keyring_cache()
    if signed:
        monkeypatch.setenv("DIALEKT_SIGNED", "1")
    else:
        monkeypatch.delenv("DIALEKT_SIGNED", raising=False)
    return secrets_mod


# ── Signed-build detection ───────────────────────────────────────────────────

def test_is_signed_darwin_build_requires_env_var(monkeypatch):
    secrets_mod = _fresh_secrets_mod(monkeypatch, signed=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert secrets_mod._is_signed_darwin_build() is False


def test_is_signed_darwin_build_with_env_var(monkeypatch):
    secrets_mod = _fresh_secrets_mod(monkeypatch, signed=True)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert secrets_mod._is_signed_darwin_build() is True


def test_is_signed_darwin_build_false_off_darwin(monkeypatch):
    secrets_mod = _fresh_secrets_mod(monkeypatch, signed=True)
    monkeypatch.setattr(sys, "platform", "linux")
    # Even with DIALEKT_SIGNED=1, non-darwin always returns False —
    # the env var is meaningful only as a macOS gate.
    assert secrets_mod._is_signed_darwin_build() is False


# ── Probe is non-mutating ────────────────────────────────────────────────────

def test_keyring_probe_does_not_write(monkeypatch):
    """The probe must NOT call set_password or delete_password.

    Earlier code did set+get+delete on a __probe__ item, which made
    'Always Allow' useless because the ACL was bound to a deleted item.
    """
    secrets_mod = _fresh_secrets_mod(monkeypatch, signed=True)
    monkeypatch.setattr(sys, "platform", "darwin")

    fake_keyring = MagicMock()
    fake_keyring.get_password.return_value = None
    fake_keyring.get_keyring.return_value = MagicMock(
        __module__="keyring.backends.macOS", __class__=type("Keyring", (), {}),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setitem(sys.modules, "keyring.backends.fail",
                        MagicMock(Keyring=type("FailKeyring", (), {})))

    ok, _ = secrets_mod._keyring_available()
    assert ok is True
    fake_keyring.get_password.assert_called_once()
    fake_keyring.set_password.assert_not_called()
    fake_keyring.delete_password.assert_not_called()


def test_keyring_disabled_on_unsigned_darwin(monkeypatch):
    secrets_mod = _fresh_secrets_mod(monkeypatch, signed=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    ok, name = secrets_mod._keyring_available()
    assert ok is False
    assert name == "disabled-macos-unsigned"


# ── Bundle round-trip ────────────────────────────────────────────────────────

def test_bundle_get_set_delete_roundtrip(monkeypatch):
    secrets_mod = _fresh_secrets_mod(monkeypatch, signed=True)
    monkeypatch.setattr(sys, "platform", "darwin")

    storage = {}

    def fake_get(service, account):
        return storage.get((service, account))

    def fake_set(service, account, value):
        storage[(service, account)] = value

    fake_keyring = MagicMock()
    fake_keyring.get_password.side_effect = fake_get
    fake_keyring.set_password.side_effect = fake_set
    fake_keyring.get_keyring.return_value = MagicMock(
        __module__="keyring.backends.macOS", __class__=type("Keyring", (), {}),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setitem(sys.modules, "keyring.backends.fail",
                        MagicMock(Keyring=type("FailKeyring", (), {})))

    secrets_mod.set_secret("license_key", "lic_abc")
    secrets_mod.set_secret("cloud_bearer_token", "tok_xyz")
    assert secrets_mod.get_secret("license_key") == "lic_abc"
    assert secrets_mod.get_secret("cloud_bearer_token") == "tok_xyz"

    # All secrets must live in ONE item, not separate ones per key.
    assert len(storage) == 1
    (service, account), raw = next(iter(storage.items()))
    assert account == secrets_mod._BUNDLE_ITEM
    bundle = json.loads(raw)
    assert bundle == {"license_key": "lic_abc", "cloud_bearer_token": "tok_xyz"}

    secrets_mod.delete_secret("license_key")
    assert secrets_mod.get_secret("license_key") is None
    assert secrets_mod.get_secret("cloud_bearer_token") == "tok_xyz"


# ── Fallback → bundle migration ──────────────────────────────────────────────

def test_migrate_fallback_to_keyring_moves_and_deletes(monkeypatch, tmp_path: Path):
    secrets_mod = _fresh_secrets_mod(monkeypatch, signed=True)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(secrets_mod, "_FALLBACK_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(secrets_mod, "_CONFIG_DIR", tmp_path)

    # Seed the fallback file via the real save path so encryption matches.
    secrets_mod._fallback_save({"license_key": "lic_old", "provider_x": "k"})
    assert secrets_mod._FALLBACK_FILE.exists()

    storage = {}
    fake_keyring = MagicMock()
    fake_keyring.get_password.side_effect = lambda s, a: storage.get((s, a))

    def fake_set(s, a, v):
        storage[(s, a)] = v
    fake_keyring.set_password.side_effect = fake_set
    fake_keyring.get_keyring.return_value = MagicMock(
        __module__="keyring.backends.macOS", __class__=type("Keyring", (), {}),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setitem(sys.modules, "keyring.backends.fail",
                        MagicMock(Keyring=type("FailKeyring", (), {})))

    rep = secrets_mod.migrate_fallback_to_keyring()
    assert sorted(rep["migrated"]) == ["license_key", "provider_x"]
    assert not secrets_mod._FALLBACK_FILE.exists(), "fallback file should be deleted"

    # Bundle now holds both secrets.
    raw = storage[(secrets_mod._SERVICE, secrets_mod._BUNDLE_ITEM)]
    assert json.loads(raw) == {"license_key": "lic_old", "provider_x": "k"}


def test_migrate_fallback_skips_when_no_keyring(monkeypatch, tmp_path: Path):
    secrets_mod = _fresh_secrets_mod(monkeypatch, signed=False)  # unsigned macOS
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(secrets_mod, "_FALLBACK_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(secrets_mod, "_CONFIG_DIR", tmp_path)
    secrets_mod._fallback_save({"license_key": "lic_old"})

    rep = secrets_mod.migrate_fallback_to_keyring()
    assert rep["skipped_no_keyring"] is True
    # File preserved — no keyring, nothing to migrate to.
    assert secrets_mod._FALLBACK_FILE.exists()


def test_migrate_fallback_noop_when_no_file(monkeypatch, tmp_path: Path):
    secrets_mod = _fresh_secrets_mod(monkeypatch, signed=True)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(secrets_mod, "_FALLBACK_FILE", tmp_path / "secrets.enc")

    fake_keyring = MagicMock()
    fake_keyring.get_password.return_value = None
    fake_keyring.get_keyring.return_value = MagicMock(
        __module__="keyring.backends.macOS", __class__=type("Keyring", (), {}),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setitem(sys.modules, "keyring.backends.fail",
                        MagicMock(Keyring=type("FailKeyring", (), {})))

    rep = secrets_mod.migrate_fallback_to_keyring()
    assert rep["skipped_no_file"] is True
    assert rep["migrated"] == []
