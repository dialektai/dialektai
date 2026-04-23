"""Regression suite for the Builder Wizard → manifest schema drift.

Each fix (F-A1 … F-A5) takes one category from failing → passing.
The tests here are written against the *target* shape each wizard
step should emit — run them against the current frontend by reading
the published agent's manifest YAML from `/agents/import-yaml`, or
(for this suite) against synthesised YAMLs that mirror what we want
the wizard to ship.

Layout mirrors docs/WIZARD_SCHEMA_DRIFT.md.
"""
import uuid
from datetime import datetime, timezone

import pytest

from dialekt_manifest import ManifestValidator


# ── Minimal valid manifest skeleton, reused by every test ────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _base_manifest(**overrides) -> str:
    """Return a schema-valid YAML with optional field overrides.

    Overrides can be any of: autonomy_recommended, autonomy_max, trigger,
    connections_block, variables_block, language, capabilities_groups.
    Shape that each override expects is documented per test below.
    """
    defaults = {
        "uuid": str(uuid.uuid4()),
        "name": "Regression Agent",
        "description": "regression test agent",
        "version": "1.0.0",
        "language": "en",
        "tags_yaml": "[]",
        "author_name": "t",
        "author_email": "t@t.t",
        "now": _now_iso(),
        "model_preferred": "llama3.2:3b",
        "acceptable_yaml": "[]",
        "min_context_window": 32768,
        "min_ram_gb": 8,
        "min_vram_gb": 0,
        "recommended_ram_gb": 16,
        "temperature": 0.7,
        "top_p": 0.95,
        "max_tokens": 4096,
        "system_prompt": "you are a test agent",
        "capabilities_groups": "[]",
        "connections_block": "",  # empty string = omit the whole field
        "variables_block": "",
        "autonomy_recommended": "ask-before-write",
        "autonomy_max": "ask-before-write",
        "input_placeholder": "Ask me anything...",
        "output_format": "markdown",
        "streaming": "true",
        "trigger": 'trigger:\n  type: "interactive"',
    }
    defaults.update(overrides)
    return (
        'spec_version: "1.0.1"\n'
        'minimum_dialekt_version: "1.0.0"\n\n'
        'metadata:\n'
        f'  id: "{defaults["uuid"]}"\n'
        f'  name: "{defaults["name"]}"\n'
        f'  description: "{defaults["description"]}"\n'
        f'  version: "{defaults["version"]}"\n'
        f'  language: "{defaults["language"]}"\n'
        f'  tags: {defaults["tags_yaml"]}\n'
        f'  author:\n'
        f'    name: "{defaults["author_name"]}"\n'
        f'    email: "{defaults["author_email"]}"\n'
        f'  created_at: "{defaults["now"]}"\n'
        f'  updated_at: "{defaults["now"]}"\n\n'
        'model:\n'
        f'  preferred: "{defaults["model_preferred"]}"\n'
        f'  acceptable: {defaults["acceptable_yaml"]}\n'
        f'  min_context_window: {defaults["min_context_window"]}\n'
        '  requirements:\n'
        f'    min_ram_gb: {defaults["min_ram_gb"]}\n'
        f'    min_vram_gb: {defaults["min_vram_gb"]}\n'
        f'    recommended_ram_gb: {defaults["recommended_ram_gb"]}\n'
        '  parameters:\n'
        f'    temperature: {defaults["temperature"]}\n'
        f'    top_p: {defaults["top_p"]}\n'
        f'    max_tokens: {defaults["max_tokens"]}\n\n'
        'system_prompt: |\n'
        f'  {defaults["system_prompt"]}\n\n'
        'capabilities:\n'
        f'  groups: {defaults["capabilities_groups"]}\n'
        + (f'\n{defaults["variables_block"]}\n' if defaults["variables_block"] else "")
        + (f'\n{defaults["connections_block"]}\n' if defaults["connections_block"] else "")
        + '\nautonomy:\n'
        f'  recommended: "{defaults["autonomy_recommended"]}"\n'
        f'  max_allowed: "{defaults["autonomy_max"]}"\n\n'
        'input:\n  type: "chat"\n'
        f'  placeholder: "{defaults["input_placeholder"]}"\n\n'
        'output:\n'
        f'  format: "{defaults["output_format"]}"\n'
        f'  streaming: {defaults["streaming"]}\n'
        '  destination:\n    type: "notification"\n\n'
        f'{defaults["trigger"]}\n'
    )


def _assert_publishes(yaml_str: str) -> None:
    result = ManifestValidator().validate_string(yaml_str)
    assert result.valid, (
        "Manifest failed validation:\n"
        + "\n".join(f"  - {e.message}" for e in result.errors)
    )


# ── F-A1: autonomy values ────────────────────────────────────────────────────


@pytest.mark.parametrize("autonomy", [
    "review-only",
    "ask-before-write",
    "autonomous",
    "sandbox-only",
    "manual",  # added 2026-04-23 so wizard's "Manual" option can publish
])
def test_all_five_autonomy_levels_publish(autonomy):
    y = _base_manifest(autonomy_recommended=autonomy, autonomy_max=autonomy)
    _assert_publishes(y)


@pytest.mark.parametrize("old_bad", ["full-auto", "ask-before-run"])
def test_pre_fix_autonomy_names_still_rejected(old_bad):
    """Guard against a revert that resurrects the old wizard-only names."""
    y = _base_manifest(autonomy_recommended=old_bad, autonomy_max=old_bad)
    result = ManifestValidator().validate_string(y)
    assert not result.valid, (
        f"Schema unexpectedly accepts {old_bad!r} — if this was intentional, "
        "update dialekt_manifest.AUTONOMY_LEVELS and this test together."
    )


# ── F-A2: connections wrapper ────────────────────────────────────────────────


_CONN_BLOCK_SINGLE_POSTGRES = (
    'connections:\n'
    '  required:\n'
    '    - type: "postgres"\n'
    '      role: "readonly"\n'
    '      purpose: "Database access for this agent"\n'
)


_CONN_BLOCK_MULTI_MIXED = (
    'connections:\n'
    '  required:\n'
    '    - type: "postgres"\n'
    '      role: "readonly"\n'
    '      purpose: "Primary analytics DB"\n'
    '    - type: "mysql"\n'
    '      role: "readonly"\n'
    '      purpose: "Secondary transactional store"\n'
)


@pytest.mark.parametrize("block,label", [
    ("",                           "no connections"),
    (_CONN_BLOCK_SINGLE_POSTGRES,  "single postgres"),
    (_CONN_BLOCK_MULTI_MIXED,      "postgres + mysql"),
])
def test_connection_variants_publish(block, label):
    y = _base_manifest(connections_block=block)
    _assert_publishes(y)


def test_wizard_old_flat_connections_rejected():
    """The pre-fix shape (flat list with id) must stay rejected —
    prevents accidental revert. Matches what wizard used to ship.
    """
    y = _base_manifest(connections_block=(
        'connections:\n'
        '  - type: "postgres"\n'
        '    id: "some-uuid"\n'
    ))
    result = ManifestValidator().validate_string(y)
    assert not result.valid


# ── F-A3: variables dict shape ───────────────────────────────────────────────


_VARS_DICT_SHAPE = (
    'variables:\n'
    '  API_KEY:\n'
    '    type: "string"\n'
    '    required: true\n'
    '    description: "External API token"\n'
    '  ENV:\n'
    '    type: "string"\n'
    '    required: false\n'
    '    description: "deployment env"\n'
)


def test_variables_dict_shape_publishes():
    y = _base_manifest(variables_block=_VARS_DICT_SHAPE)
    _assert_publishes(y)


@pytest.mark.parametrize("var_type", ["string", "number", "boolean", "list"])
def test_each_variable_type_publishes(var_type):
    block = (
        'variables:\n'
        '  SOMEVAR:\n'
        f'    type: "{var_type}"\n'
        '    required: false\n'
        '    description: "a variable"\n'
    )
    y = _base_manifest(variables_block=block)
    _assert_publishes(y)


def test_wizard_old_array_variables_rejected():
    """Pre-fix wizard emitted `- key: X, description: Y, required: Z`
    as a YAML array. Keep it rejected so a revert shows up in CI.
    """
    y = _base_manifest(variables_block=(
        'variables:\n'
        '  - key: "API_KEY"\n'
        '    description: "An API key"\n'
        '    required: true\n'
    ))
    result = ManifestValidator().validate_string(y)
    assert not result.valid


# ── F-A4: language — Kazakh ──────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["en", "ru", "kk", "multi"])
def test_all_exposed_languages_publish(lang):
    y = _base_manifest(language=lang)
    _assert_publishes(y)


# ── F-A5: trigger — only interactive publishes today ─────────────────────────


def test_interactive_trigger_publishes():
    _assert_publishes(_base_manifest())


@pytest.mark.parametrize("bad_trigger", [
    # These three are offered in the wizard UI but are not valid schema
    # triggers today (scheduled needs more fields; webhook + event
    # aren't in the schema at all). The wizard gates Publish on them
    # (F-A5); the schema confirms they fail if anything slips through.
    'trigger:\n  type: "webhook"',
    'trigger:\n  type: "event"',
    'trigger:\n  type: "scheduled"',  # missing schedule / timezone
])
def test_unsupported_triggers_rejected_by_schema(bad_trigger):
    y = _base_manifest(trigger=bad_trigger)
    result = ManifestValidator().validate_string(y)
    assert not result.valid, (
        f"Schema unexpectedly accepts trigger block:\n{bad_trigger}\n— "
        "update the wizard gate or schema together."
    )


# ── End-to-end scenarios (A–E) from docs/WIZARD_SCHEMA_DRIFT.md ──────────────


def _scenario_A():
    # SQL Analyst — single postgres connection, DB+network caps,
    # autonomy laddered (ask-before-write recommended / autonomous ceiling).
    return _base_manifest(
        name="Test SQL Analyst",
        capabilities_groups='["database_read", "network"]',
        connections_block=_CONN_BLOCK_SINGLE_POSTGRES,
        autonomy_recommended="ask-before-write",
        autonomy_max="autonomous",
    )


def _scenario_B():
    # Pure LLM, no DB, review-only on both.
    return _base_manifest(
        name="Pure LLM",
        autonomy_recommended="review-only",
        autonomy_max="review-only",
    )


def _scenario_C():
    # Power user — all caps + two variables + mysql + autonomous.
    return _base_manifest(
        name="Power Agent",
        capabilities_groups=(
            '["filesystem_read", "network", "browser", "database_read", '
            '"shell_execute", "screen_capture"]'
        ),
        connections_block=(
            'connections:\n'
            '  required:\n'
            '    - type: "mysql"\n'
            '      role: "readonly"\n'
            '      purpose: "Database access for this agent"\n'
        ),
        variables_block=_VARS_DICT_SHAPE,
        autonomy_recommended="autonomous",
        autonomy_max="autonomous",
    )


def _scenario_D():
    # Minimal — only required fields, everything else default.
    return _base_manifest()


def _scenario_E():
    # Sandbox postgres analyst.
    return _base_manifest(
        name="Sandbox Analyst",
        capabilities_groups='["database_read"]',
        connections_block=_CONN_BLOCK_SINGLE_POSTGRES,
        autonomy_recommended="sandbox-only",
        autonomy_max="sandbox-only",
    )


@pytest.mark.parametrize("scenario,label", [
    (_scenario_A, "A (SQL Analyst)"),
    (_scenario_B, "B (Pure LLM)"),
    (_scenario_C, "C (Power user)"),
    (_scenario_D, "D (Minimal)"),
    (_scenario_E, "E (Sandbox)"),
])
def test_wizard_scenario_publishes(scenario, label):
    """Each of the five realistic wizard scenarios must publish."""
    _assert_publishes(scenario())
