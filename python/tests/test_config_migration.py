"""
Smoke test: settings migration from ~/.config/dialekt/ to ~/.dialekt/.
Patches module-level path constants — does not touch real config files.
"""
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

import server


@contextmanager
def _isolated_config(tmp: Path):
    """Redirect server's config paths to a temp dir for the duration of a test."""
    new_cfg = tmp / "new" / "config.json"
    old_cfg = tmp / "old" / "settings.json"

    orig_settings   = server.SETTINGS_FILE
    orig_old        = server.OLD_SETTINGS_FILE

    server.SETTINGS_FILE    = new_cfg
    server.OLD_SETTINGS_FILE = old_cfg
    try:
        yield new_cfg, old_cfg
    finally:
        server.SETTINGS_FILE    = orig_settings
        server.OLD_SETTINGS_FILE = orig_old


def test_fresh_install_uses_defaults():
    """No config files → load_settings returns DEFAULT_SETTINGS without crashing."""
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_config(Path(tmp)) as (new_cfg, old_cfg):
            assert not new_cfg.exists()
            assert not old_cfg.exists()

            settings = server.load_settings()
            assert settings["model"] == server.DEFAULT_SETTINGS["model"]
            assert settings["autonomy"] == server.DEFAULT_SETTINGS["autonomy"]
            # No file should be auto-created by a plain load
            assert not new_cfg.exists()


def test_existing_new_config_loaded():
    """~/.dialekt/config.json present → loaded directly."""
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_config(Path(tmp)) as (new_cfg, _):
            new_cfg.parent.mkdir(parents=True)
            custom = {**server.DEFAULT_SETTINGS, "model": "custom-model", "autonomy": "auto"}
            new_cfg.write_text(json.dumps(custom))

            settings = server.load_settings()
            assert settings["model"] == "custom-model"
            assert settings["autonomy"] == "auto"


def test_old_config_migrated_to_new_location():
    """Old config exists, new does not → auto-migrate; values preserved; new file created."""
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_config(Path(tmp)) as (new_cfg, old_cfg):
            old_cfg.parent.mkdir(parents=True)
            old_data = {**server.DEFAULT_SETTINGS, "model": "old-model", "temperature": 0.3}
            old_cfg.write_text(json.dumps(old_data))

            assert not new_cfg.exists()
            settings = server.load_settings()

            assert settings["model"] == "old-model"
            assert abs(settings["temperature"] - 0.3) < 1e-9

            assert new_cfg.exists(), "Migration did not create new config file"
            migrated = json.loads(new_cfg.read_text())
            assert migrated["model"] == "old-model"


def test_new_config_takes_priority_over_old():
    """Both config files exist → new location wins, old is ignored."""
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_config(Path(tmp)) as (new_cfg, old_cfg):
            new_cfg.parent.mkdir(parents=True)
            old_cfg.parent.mkdir(parents=True)
            new_cfg.write_text(json.dumps({**server.DEFAULT_SETTINGS, "model": "new-wins"}))
            old_cfg.write_text(json.dumps({**server.DEFAULT_SETTINGS, "model": "old-loses"}))

            settings = server.load_settings()
            assert settings["model"] == "new-wins"


def test_save_settings_creates_parent_dir():
    """save_settings auto-creates the parent directory."""
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_config(Path(tmp)) as (new_cfg, _):
            assert not new_cfg.parent.exists()
            server.save_settings({"model": "saved", "autonomy": "ask"})
            assert new_cfg.exists()
            saved = json.loads(new_cfg.read_text())
            assert saved["model"] == "saved"


def test_corrupt_config_falls_back_to_defaults():
    """Corrupt config.json → falls back to DEFAULT_SETTINGS without crashing."""
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_config(Path(tmp)) as (new_cfg, _):
            new_cfg.parent.mkdir(parents=True)
            new_cfg.write_text("{invalid json{{{{")

            settings = server.load_settings()
            assert settings["model"] == server.DEFAULT_SETTINGS["model"]


def test_dynamic_username_in_system_prompt():
    """System prompt references current runtime user, not a hardcoded username."""
    import getpass
    prompt = server.DEFAULT_SETTINGS["system_prompt"]
    current = getpass.getuser()
    # If we're running as 'dias', the prompt will say 'dias' — that's fine (dynamic)
    # But if running as any other user, 'dias' must NOT appear
    if current != "dias":
        assert "dias" not in prompt, \
            "System prompt contains hardcoded 'dias' — should use getpass.getuser()"
    assert "briq_pg_2026" not in prompt


def test_no_pg_dsn_attribute():
    """PG_DSN with embedded credentials must not exist on the server module."""
    assert not hasattr(server, "PG_DSN"), \
        "PG_DSN found on server module — embedded credentials still present"


def test_no_asyncpg_import():
    """asyncpg must not be imported in the server module."""
    import sys
    # asyncpg may be installed, but server.py should not import it at module level
    # We verify by checking that 'pool' (the asyncpg pool) doesn't exist
    assert not hasattr(server, "pool"), \
        "server.pool found — asyncpg pool still present"
    # Also verify db (aiosqlite connection) is the expected attribute
    assert hasattr(server, "db"), "server.db (aiosqlite connection) not found"
