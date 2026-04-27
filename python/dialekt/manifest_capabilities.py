"""Runtime extension of the manifest schema's CAPABILITY_GROUPS set.

The validator package ``dialekt-manifest-validator`` ships its
``CAPABILITY_GROUPS`` constant frozen to whatever the current PyPI release
declares (v0.1.0 at time of writing: filesystem_*, database_*, shell_execute,
network, browser, screen_capture, mcp_tools).

We need to ship new capability groups (``web_search`` first; later cms_write,
etc.) ahead of pushing them upstream + bumping the dependency. Doing it as
an additive runtime patch is safe because:

1. ``CAPABILITY_GROUPS`` is a plain Python ``set`` — mutable.
2. Validation is ``set(v) - CAPABILITY_GROUPS`` (schema.py:143) — adding to
   the set widens what's accepted; existing manifests keep validating.
3. Per the upstream spec doc, additive capability changes don't require a
   spec_version bump (it stays 1.1.0). When the next validator release
   ships these natively, this module becomes a no-op (the .add() calls are
   idempotent on a set) and can be deleted.

TODO(post-validator-0.1.1): once ``dialekt-manifest-validator`` >= 0.1.1
ships these capabilities natively, delete this file and the import line in
``python/dialekt/__init__.py``. Confirm by checking
``CAPABILITY_GROUPS >= EXTRA_CAPABILITY_GROUPS`` against the upstream
constant.
"""

from __future__ import annotations

import logging

log = logging.getLogger("dialekt.manifest_capabilities")


# Capability groups added by this dialekt build, ahead of the validator
# package shipping them. Keep small and intentional — every entry is a
# promise that we have runtime support for that capability somewhere in
# the codebase, not just a parser flag.
EXTRA_CAPABILITY_GROUPS: frozenset[str] = frozenset({
    "web_search",
})


def apply_runtime_patch() -> tuple[set[str], set[str]]:
    """Add ``EXTRA_CAPABILITY_GROUPS`` to the upstream validator's set.

    Returns ``(added, already_present)`` so callers — and tests — can see
    which groups were genuinely new vs. already shipped upstream.
    Idempotent: calling this twice is a no-op the second time.
    """
    try:
        from dialekt_manifest import schema as _schema
    except ImportError:
        log.warning(
            "dialekt-manifest-validator not importable — capability patch skipped"
        )
        return set(), set()

    target = _schema.CAPABILITY_GROUPS
    added: set[str] = set()
    already_present: set[str] = set()
    for cap in EXTRA_CAPABILITY_GROUPS:
        if cap in target:
            already_present.add(cap)
        else:
            target.add(cap)
            added.add(cap)

    if added:
        log.info(
            "extended manifest CAPABILITY_GROUPS with %s "
            "(remove this patch once validator ships them natively)",
            sorted(added),
        )
    return added, already_present


# Apply on import so any code path that imports `dialekt` — including the
# FastAPI server's `from dialekt.secrets import ...` — gets the widened
# set before the validator is invoked.
apply_runtime_patch()
