"""Library catalog seeder.

The v1 curation pipeline is git-tracked: edit `LIBRARY_TEMPLATES`,
re-deploy, the cloud does an idempotent upsert into `library_entries`
on startup. v2 will move authoring to a founder admin UI but that's
deferred until manual curation hits a real bottleneck (mentor call).

Each template's category + tags are declared here (curation surface);
the manifest YAML is the agent's behavior. requires_connection and
requires_mcp are computed from the manifest at seed time so the catalog
listing endpoint can filter without parsing every YAML at request time.

NO `pilot_source` / `installed_count` / `verified` / `complexity` /
`setup_time_minutes` fields exist — see the architectural review for
why each was rejected for v1. NO client / pilot identifiers in agent
names or descriptions (information leak risk).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import textwrap
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LibraryTemplate:
    id: str            # stable slug, used as primary key
    category: str
    tags: tuple[str, ...]
    manifest_yaml: str
    version: str = "1.0.0"


def _yaml(s: str) -> str:
    """Trim leading newline + dedent, so manifests can be authored as
    triple-quoted Python strings without leading-space contamination."""
    return textwrap.dedent(s).lstrip("\n")


_SQL_BASE_PROMPT = """\
You are a read-only {dialect} SQL assistant.
Connection ID: {{{{connection_id}}}}
Respond in the same language as the user (Russian, English, or Kazakh).

CORE RULES:
1. NEVER execute destructive SQL. Only SELECT / SHOW / EXPLAIN are allowed.
2. ALWAYS show the SQL query to the user BEFORE executing it. Wait for confirmation
   on the first query of a session.
3. For ambiguous requests, ask a clarifying question instead of guessing.
4. Format results as markdown tables with human-readable numbers (thousands separator).
5. If a query may return >10k rows, add LIMIT and warn the user.
6. For aggregation questions, prefer a single SQL with GROUP BY over multiple
   round-trips. The user pays per-second, not per-query.

DATABASE TOOLS — call via Python httpx (auto-injected base URL):
- POST /db/query  body: {{{{"connection_id": "...", "sql": "..."}}}}
"""


_SQL_TEMPLATE = """\
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"
metadata:
  id: "__REPLACE__"
  name: "{name}"
  description: "{description}"
  version: "1.0.0"
  language: multi
  author:
    name: "dias.now"
    email: "hello@dias.now"
model:
  preferred: "qwen2.5-coder:7b"
  acceptable:
    - "qwen2.5-coder:14b"
    - "gemma3:12b"
    - "mistral:7b"
  min_context_window: 16384
  requirements:
    min_ram_gb: 8
    recommended_ram_gb: 16
  parameters:
    temperature: 0.1
    top_p: 0.95
    max_tokens: 4096
system_prompt: |
  {prompt_indented}
connections:
  - id: "{{{{connection_id}}}}"
    type: "{conn_type}"
    required: true
capabilities:
  groups:
    - sql_read
"""


def _make_sql(slug: str, dialect: str, conn_type: str) -> str:
    name = f"SQL Analyst ({dialect})"
    description = f"Read-only {dialect} SQL assistant. Shows queries before executing. Multilingual."
    prompt = _SQL_BASE_PROMPT.format(dialect=dialect)
    prompt_indented = "\n  ".join(prompt.splitlines())
    return _SQL_TEMPLATE.format(
        name=name, description=description,
        prompt_indented=prompt_indented, conn_type=conn_type,
    )


LIBRARY_TEMPLATES: tuple[LibraryTemplate, ...] = (
    LibraryTemplate(
        id="sql-analyst-postgres",
        category="data-analytics",
        tags=("sql", "postgresql", "analytics"),
        manifest_yaml=_make_sql("sql-analyst-postgres", "PostgreSQL", "postgres"),
    ),
    LibraryTemplate(
        id="sql-analyst-mysql",
        category="data-analytics",
        tags=("sql", "mysql", "analytics"),
        manifest_yaml=_make_sql("sql-analyst-mysql", "MySQL", "mysql"),
    ),
    LibraryTemplate(
        id="sql-analyst-clickhouse",
        category="data-analytics",
        tags=("sql", "clickhouse", "analytics", "events"),
        manifest_yaml=_make_sql("sql-analyst-clickhouse", "ClickHouse", "clickhouse"),
    ),
    LibraryTemplate(
        id="python-code-reviewer",
        category="development",
        tags=("python", "code-review", "linting"),
        manifest_yaml=_yaml("""
            spec_version: "1.0.1"
            minimum_dialekt_version: "1.0.0"
            metadata:
              id: "__REPLACE__"
              name: "Python Code Reviewer"
              description: "Reviews Python code for bugs, style, and idiomatic patterns. Read-only — never edits files."
              version: "1.0.0"
              language: multi
              author:
                name: "dias.now"
                email: "hello@dias.now"
            model:
              preferred: "qwen2.5-coder:7b"
              acceptable:
                - "qwen2.5-coder:14b"
                - "gemma3:12b"
              min_context_window: 16384
              requirements:
                min_ram_gb: 8
                recommended_ram_gb: 16
              parameters:
                temperature: 0.2
                max_tokens: 4096
            system_prompt: |
              You are a senior Python code reviewer.
              Respond in the same language as the user (Russian or English).

              When the user shares code:
              1. Identify bugs (runtime errors, off-by-one, race conditions, etc.) FIRST.
              2. Then call out style / idiom issues (PEP 8, type hints, comprehensions vs loops).
              3. Suggest concrete refactors, not vague advice. Show the rewritten snippet.
              4. If you'd flag a concern but aren't certain, say "I'd double-check ..." rather than asserting.

              You can READ files via the filesystem tool. You do NOT edit files —
              if the user asks for a fix, output the corrected code in the chat for them to apply.
            capabilities:
              groups:
                - filesystem_read
        """),
    ),
    LibraryTemplate(
        id="bash-helper",
        category="development",
        tags=("bash", "shell", "linux"),
        manifest_yaml=_yaml("""
            spec_version: "1.0.1"
            minimum_dialekt_version: "1.0.0"
            metadata:
              id: "__REPLACE__"
              name: "Bash Helper"
              description: "Suggests safe shell commands. Review-only autonomy — every command is shown for confirmation before running."
              version: "1.0.0"
              language: multi
              author:
                name: "dias.now"
                email: "hello@dias.now"
            model:
              preferred: "qwen2.5-coder:7b"
              acceptable:
                - "qwen2.5-coder:14b"
                - "gemma3:12b"
              min_context_window: 8192
              requirements:
                min_ram_gb: 8
                recommended_ram_gb: 16
              parameters:
                temperature: 0.2
                max_tokens: 2048
            system_prompt: |
              You are a Bash / Linux command-line assistant.
              Respond in the same language as the user (Russian or English).

              RULES:
              1. ALWAYS show the command BEFORE running. The autonomy mode is review-only —
                 the user must approve every shell call.
              2. Refuse anything destructive on first try (rm -rf, dd to a device, mkfs,
                 force-push, drop database). Explain what it does and ask if the user
                 really means it.
              3. Prefer composed pipelines using POSIX tools over scripts where possible.
              4. When suggesting a command, also show how to dry-run / preview it
                 (--dry-run, -n, etc.) when the tool supports it.
            capabilities:
              groups:
                - shell_review_only
        """),
    ),
    LibraryTemplate(
        id="document-summarizer",
        category="documents",
        tags=("summary", "documents", "reading"),
        manifest_yaml=_yaml("""
            spec_version: "1.0.1"
            minimum_dialekt_version: "1.0.0"
            metadata:
              id: "__REPLACE__"
              name: "Document Summarizer"
              description: "Three-bullet extractive summary of any pasted text or local document. No connections, no setup."
              version: "1.0.0"
              language: multi
              author:
                name: "dias.now"
                email: "hello@dias.now"
            model:
              preferred: "gemma3:12b"
              acceptable:
                - "qwen2.5:7b"
                - "mistral:7b"
              min_context_window: 16384
              requirements:
                min_ram_gb: 8
                recommended_ram_gb: 16
              parameters:
                temperature: 0.3
                max_tokens: 1024
            system_prompt: |
              You are a document summarizer.
              Respond in the same language as the document.

              For any text the user pastes (or a file they share):
              1. Output exactly three bullets, each one sentence.
              2. The first bullet captures the main claim. The second bullet captures
                 the strongest supporting point. The third bullet captures the most
                 important caveat, limitation, or counter-argument.
              3. NEVER add a preamble like "Here is the summary:" — start with "•".
              4. If the document is shorter than 200 words, return one bullet only and
                 say "Document too short for three-bullet structure".
            capabilities:
              groups:
                - filesystem_read
        """),
    ),
    LibraryTemplate(
        id="translator-ru-en",
        category="documents",
        tags=("translation", "russian", "english"),
        manifest_yaml=_yaml("""
            spec_version: "1.0.1"
            minimum_dialekt_version: "1.0.0"
            metadata:
              id: "__REPLACE__"
              name: "RU/EN Translator"
              description: "Bidirectional Russian ↔ English translation. Preserves formatting, technical terms, and tone."
              version: "1.0.0"
              language: multi
              author:
                name: "dias.now"
                email: "hello@dias.now"
            model:
              preferred: "gemma3:12b"
              acceptable:
                - "qwen2.5:7b"
                - "mistral:7b"
              min_context_window: 16384
              requirements:
                min_ram_gb: 8
                recommended_ram_gb: 16
              parameters:
                temperature: 0.2
                max_tokens: 4096
            system_prompt: |
              You are a Russian ↔ English translator.

              RULES:
              1. Detect the source language. If it's Russian, translate to English. If it's
                 English, translate to Russian. If the user explicitly asks for a direction,
                 follow it.
              2. Preserve markdown formatting (headings, lists, code blocks, links). Do NOT
                 translate code content inside ``` blocks; do translate comments inside.
              3. Keep technical terms (API, JSON, SDK, etc.) as-is unless the user has
                 specified a glossary in this session.
              4. Output the translation only — no preamble, no apologies. If the input is
                 ambiguous, ask one clarifying question instead of guessing.
        """),
    ),
)


def compute_signature(manifest_yaml: str, secret: str) -> str:
    """HMAC-SHA256 of the manifest, hex-encoded. Desktop verifies on
    cache to detect tamper at rest."""
    return hmac.new(
        secret.encode("utf-8"),
        manifest_yaml.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _derive_flags(manifest_yaml: str) -> tuple[bool, bool]:
    """Compute requires_connection / requires_mcp from the manifest."""
    requires_connection = "connections:" in manifest_yaml and "required: true" in manifest_yaml
    requires_mcp = "mcp_tools" in manifest_yaml or "mcp_servers:" in manifest_yaml
    return requires_connection, requires_mcp


async def seed_library_entries(pool) -> int:
    """Idempotent upsert of LIBRARY_TEMPLATES into library_entries.
    Returns the number of rows touched. Safe to call on every boot.

    Signature uses DIALEKT_LIBRARY_HMAC_SECRET — when unset (e.g. dev),
    the column is left NULL and desktop skips integrity verification."""
    secret = os.environ.get("DIALEKT_LIBRARY_HMAC_SECRET", "")
    touched = 0
    async with pool.acquire() as conn:
        for tpl in LIBRARY_TEMPLATES:
            requires_connection, requires_mcp = _derive_flags(tpl.manifest_yaml)
            signature = compute_signature(tpl.manifest_yaml, secret) if secret else None
            await conn.execute(
                """
                INSERT INTO library_entries(
                    id, manifest_yaml, category, tags,
                    requires_connection, requires_mcp,
                    signature, version, published, updated_at
                ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,TRUE,now())
                ON CONFLICT(id) DO UPDATE SET
                    manifest_yaml = EXCLUDED.manifest_yaml,
                    category = EXCLUDED.category,
                    tags = EXCLUDED.tags,
                    requires_connection = EXCLUDED.requires_connection,
                    requires_mcp = EXCLUDED.requires_mcp,
                    signature = EXCLUDED.signature,
                    version = EXCLUDED.version,
                    updated_at = now()
                """,
                tpl.id, tpl.manifest_yaml, tpl.category,
                json.dumps(list(tpl.tags)),
                requires_connection, requires_mcp,
                signature, tpl.version,
            )
            touched += 1
    logger.info("library_entries seeded: %d rows", touched)
    return touched
