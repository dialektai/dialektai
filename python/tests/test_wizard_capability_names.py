"""Guard that Wizard Step 4's capability keys stay schema-valid.

History: before 2026-04-23 the wizard emitted `filesystem`, `terminal`,
`screen` — all rejected by dialekt_manifest.ManifestValidator with
`Unknown capability groups`, breaking publish for any agent that ticked
those boxes. This test pins the names so the wizard can't silently
regress.

The frontend CAP_META keys at `frontend/src/screens/AgentWizardScreen.jsx`
are mirrored here. Keep both in sync; if someone adds a new group in the
UI, add it here too.
"""
import uuid

import pytest

from dialekt_manifest import ManifestValidator

WIZARD_CAPABILITY_KEYS = [
    "filesystem_read",
    "network",
    "browser",
    "database_read",
    "shell_execute",
    "screen_capture",
]


def _manifest_with_groups(groups: list[str]) -> str:
    groups_yaml = "[" + ", ".join(f'"{g}"' for g in groups) + "]" if groups else "[]"
    return f"""spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"
metadata:
  id: "{uuid.uuid4()}"
  name: "t"
  description: "t"
  version: "1.0.0"
  language: "en"
  tags: []
  author:
    name: "t"
    email: "t@t.t"
  created_at: "2026-04-23T00:00:00+00:00"
  updated_at: "2026-04-23T00:00:00+00:00"
model:
  preferred: "gemma3-12b"
  acceptable: []
  min_context_window: 8192
  requirements:
    min_ram_gb: 8
    min_vram_gb: 0
    recommended_ram_gb: 16
  parameters:
    temperature: 0.7
    top_p: 0.95
    max_tokens: 2048
system_prompt: |
  t
capabilities:
  groups: {groups_yaml}
autonomy:
  recommended: "ask-before-write"
  max_allowed: "ask-before-write"
input:
  type: "chat"
  placeholder: "x"
output:
  format: "markdown"
  streaming: true
  destination:
    type: "notification"
trigger:
  type: "interactive"
"""


@pytest.mark.parametrize("group", WIZARD_CAPABILITY_KEYS)
def test_each_wizard_capability_name_is_schema_valid(group):
    result = ManifestValidator().validate_string(_manifest_with_groups([group]))
    assert result.valid, (
        f"Wizard capability key {group!r} fails manifest validation:\n"
        + "\n".join(f"  - {e.message}" for e in result.errors)
    )


def test_all_six_wizard_capabilities_together_publish_cleanly():
    """When a user ticks every checkbox, the emitted manifest must still validate."""
    result = ManifestValidator().validate_string(
        _manifest_with_groups(WIZARD_CAPABILITY_KEYS)
    )
    assert result.valid, (
        "Full-house wizard capabilities manifest fails validation:\n"
        + "\n".join(f"  - {e.message}" for e in result.errors)
    )


def test_old_invalid_names_still_rejected():
    """Regression guard — the pre-fix names must stay rejected so we
    catch any accidental revert to `filesystem`/`terminal`/`screen`.
    """
    for bad in ("filesystem", "terminal", "screen"):
        result = ManifestValidator().validate_string(_manifest_with_groups([bad]))
        assert not result.valid, (
            f"Schema unexpectedly accepts {bad!r} — please update this "
            "test and probably rename the CAPABILITY_GROUPS set in dialekt_manifest."
        )
