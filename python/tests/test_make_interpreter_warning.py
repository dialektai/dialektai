"""Tests for make_interpreter's model.parameters advisory-only warning.

A manifest may set ``model.parameters.temperature`` or ``model.parameters.max_tokens``.
These values are ignored at runtime — global settings always win. Since
the conflict is silent, make_interpreter must emit a log.warning so operators
(IBA pilot staff) know why their deterministic temperature setting is not effective.

All tests run without Open Interpreter or Ollama installed.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))


_MINIMAL_SETTINGS = {
    "model": "gemma3:12b",
    "model_provider": "ollama",
    "context_window": 8192,
    "max_tokens": 4096,
    "temperature": 0.7,
}


def _fake_interpreter():
    itp = MagicMock()
    itp.computer.terminal.languages = []
    return itp


def _call_make_interpreter(agent: dict, fake_itp=None):
    """Call make_interpreter with all heavy deps mocked out."""
    if fake_itp is None:
        fake_itp = _fake_interpreter()
    fake_module = MagicMock()
    fake_module.interpreter = fake_itp

    with patch.dict(sys.modules, {"interpreter": fake_module}), \
         patch("server.load_settings", return_value=_MINIMAL_SETTINGS), \
         patch("server.get_installed_ollama_models", return_value=["qwen2.5-coder:7b", "gemma3:12b"]), \
         patch("server.pick_model_for_agent", return_value="gemma3:12b"), \
         patch("dialekt.llm.resolver.resolve_litellm_model", return_value={}), \
         patch("dialekt.llm.resolver.apply_to_interpreter"), \
         patch("dialekt.llm.prompt_wrapper.should_wrap", return_value=False), \
         patch("dialekt.llm.prompt_wrapper.substitute_template_vars", side_effect=lambda p, **_: p):
        from server import make_interpreter
        make_interpreter(agent)


# ---------------------------------------------------------------------------
# Warning emitted when manifest sets temperature
# ---------------------------------------------------------------------------

def test_temperature_override_warning_emitted(caplog):
    """A manifest with temperature=0.1 must trigger a runtime warning."""
    manifest = yaml.dump({
        "spec_version": "1.0.1",
        "name": "schedule_planner",
        "model": {
            "preferred": "qwen2.5-coder:7b",
            "parameters": {"temperature": 0.1},
        },
        "trigger": {"type": "interactive"},
    })
    agent = {
        "name": "schedule_planner",
        "manifest_yaml": manifest,
        "system_prompt": "You are a scheduler.",
    }

    with caplog.at_level(logging.WARNING, logger="server"):
        _call_make_interpreter(agent)

    assert any(
        "model.parameters" in r.message and "temperature=0.1" in r.message
        for r in caplog.records
    ), f"Expected warning not found. Records: {[r.message for r in caplog.records]}"


def test_max_tokens_override_warning_emitted(caplog):
    """A manifest with max_tokens=4096 must also trigger the warning."""
    manifest = yaml.dump({
        "spec_version": "1.0.1",
        "name": "content_editor",
        "model": {
            "preferred": "gemma3:12b",
            "parameters": {"max_tokens": 2048},
        },
        "trigger": {"type": "interactive"},
    })
    agent = {
        "name": "content_editor",
        "manifest_yaml": manifest,
        "system_prompt": "You are an editor.",
    }

    with caplog.at_level(logging.WARNING, logger="server"):
        _call_make_interpreter(agent)

    assert any(
        "model.parameters" in r.message and "max_tokens=2048" in r.message
        for r in caplog.records
    )


def test_both_overrides_reported_in_single_warning(caplog):
    """When both temperature and max_tokens are set both should appear in one warning."""
    manifest = yaml.dump({
        "spec_version": "1.0.1",
        "name": "strict_agent",
        "model": {
            "preferred": "gemma3:12b",
            "parameters": {"temperature": 0.0, "max_tokens": 512},
        },
        "trigger": {"type": "interactive"},
    })
    agent = {
        "name": "strict_agent",
        "manifest_yaml": manifest,
        "system_prompt": "Be strict.",
    }

    with caplog.at_level(logging.WARNING, logger="server"):
        _call_make_interpreter(agent)

    warning_msgs = [r.message for r in caplog.records if "model.parameters" in r.message]
    assert len(warning_msgs) == 1, "Expected exactly one parameters warning"
    assert "temperature=0.0" in warning_msgs[0]
    assert "max_tokens=512" in warning_msgs[0]


def test_no_warning_when_manifest_omits_parameters(caplog):
    """Manifests that do not set model.parameters must not emit the warning."""
    manifest = yaml.dump({
        "spec_version": "1.0.1",
        "name": "smm_manager",
        "model": {"preferred": "gemma3:12b"},
        "trigger": {"type": "interactive"},
    })
    agent = {
        "name": "smm_manager",
        "manifest_yaml": manifest,
        "system_prompt": "Write social posts.",
    }

    with caplog.at_level(logging.WARNING, logger="server"):
        _call_make_interpreter(agent)

    assert not any(
        "model.parameters" in r.message for r in caplog.records
    ), "Unexpected parameters warning"


def test_no_warning_when_no_agent_manifest(caplog):
    """Bare make_interpreter() call without an agent must not warn."""
    with caplog.at_level(logging.WARNING, logger="server"):
        _call_make_interpreter(agent=None)

    assert not any(
        "model.parameters" in r.message for r in caplog.records
    )
