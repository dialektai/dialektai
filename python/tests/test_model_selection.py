"""Tests for pick_model_for_agent — manifest-driven model routing.

The agent runtime must pick a model from the agent's manifest when possible,
falling back sensibly before reaching the global default. Regression guard
for the 'SQL Analyst ran on gemma3-12b even though manifest said
qwen2.5-coder' bug.
"""
import pytest

from server import pick_model_for_agent


def test_preferred_model_used_when_installed():
    manifest = {"model": {"preferred": "qwen2.5-coder:7b"}}
    installed = {"qwen2.5-coder:7b", "gemma3-12b:latest"}
    assert pick_model_for_agent(manifest, installed, "gemma3-12b") == "qwen2.5-coder:7b"


def test_acceptable_fallback_when_preferred_missing():
    manifest = {
        "model": {
            "preferred": "qwen2.5-coder:32b",
            "acceptable": ["qwen2.5-coder:14b", "mistral:7b"],
        }
    }
    installed = {"mistral:7b", "gemma3-12b:latest"}
    assert pick_model_for_agent(manifest, installed, "gemma3-12b") == "mistral:7b"


def test_family_match_fallback_preferred():
    """Critical: manifest says :32b, only :7b installed — should family-match."""
    manifest = {"model": {"preferred": "qwen2.5-coder:32b"}}
    installed = {"qwen2.5-coder:7b", "gemma3-12b:latest"}
    assert pick_model_for_agent(manifest, installed, "gemma3-12b") == "qwen2.5-coder:7b"


def test_family_match_from_acceptable():
    """When preferred has no family match, try families of acceptable list."""
    manifest = {
        "model": {
            "preferred": "llama3:70b",
            "acceptable": ["qwen2.5-coder:14b"],
        }
    }
    # No llama3:* installed, but qwen2.5-coder:7b matches family of the acceptable 14b.
    installed = {"qwen2.5-coder:7b", "gemma3-12b:latest"}
    assert pick_model_for_agent(manifest, installed, "gemma3-12b") == "qwen2.5-coder:7b"


def test_default_when_nothing_matches():
    manifest = {"model": {"preferred": "llama3:8b"}}
    installed = {"gemma3-12b:latest"}
    assert pick_model_for_agent(manifest, installed, "gemma3-12b") == "gemma3-12b"


def test_no_manifest_uses_default():
    installed = {"gemma3-12b:latest"}
    assert pick_model_for_agent({}, installed, "gemma3-12b") == "gemma3-12b"


def test_none_manifest_uses_default():
    assert pick_model_for_agent(None, {"gemma3-12b:latest"}, "gemma3-12b") == "gemma3-12b"


def test_empty_installed_set_uses_default():
    manifest = {"model": {"preferred": "qwen2.5-coder:7b"}}
    assert pick_model_for_agent(manifest, set(), "gemma3-12b") == "gemma3-12b"
