"""Universal action audit log for the dialekt desktop backend.

See ``log.py`` for the public API and ``docs/M2_MCP_DESIGN.md``
Decision 7 for the design rationale.
"""
from dialekt.audit.log import AUDIT_SCHEMA, log_event

__all__ = ["AUDIT_SCHEMA", "log_event"]
