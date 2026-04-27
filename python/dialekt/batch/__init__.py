"""Batch processing — run an agent over multiple files in one job.

Public surface:
- ``BATCH_SCHEMA``: DDL string. Mirrored into ``server._SCHEMA`` so the
  main DB picks the tables up at startup. The duplication is the same
  pattern the audit log uses (``dialekt.audit.AUDIT_SCHEMA``) — keeps
  this module testable in isolation while still being part of the one
  startup migration path.
- ``Job``, ``BatchFile``: dataclasses returned by the CRUD helpers.
- ``create_job``, ``get_job``, ``list_files``, ``set_status``,
  ``record_file_*``: thin async wrappers over ``aiosqlite``.

Per-file outputs live on disk under
``~/.dialekt/batch/<job_id>/<input_basename>.<ext>`` so a long batch
does not bloat SQLite. The DB only tracks pointers + status.
"""
from .job import (
    BATCH_SCHEMA,
    Job,
    BatchFile,
    JOB_STATUSES,
    FILE_STATUSES,
    create_job,
    get_job,
    list_files,
    set_job_status,
    set_job_error,
    increment_done,
    record_file_started,
    record_file_done,
    record_file_error,
    record_file_cancelled,
)

__all__ = [
    "BATCH_SCHEMA",
    "Job",
    "BatchFile",
    "JOB_STATUSES",
    "FILE_STATUSES",
    "create_job",
    "get_job",
    "list_files",
    "set_job_status",
    "set_job_error",
    "increment_done",
    "record_file_started",
    "record_file_done",
    "record_file_error",
    "record_file_cancelled",
]
