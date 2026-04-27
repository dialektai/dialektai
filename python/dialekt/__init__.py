"""dialekt package init.

We intentionally trigger one runtime side-effect on import: the manifest
capability patch. This widens ``dialekt_manifest.schema.CAPABILITY_GROUPS``
with the capability groups this build ships ahead of the validator's PyPI
release (e.g. ``web_search``). Doing it here means every code path that
talks to dialekt — server boot, tests, CLI — picks the patch up before
any manifest is validated. See ``dialekt.manifest_capabilities``.
"""

from . import manifest_capabilities as _manifest_capabilities  # noqa: F401
