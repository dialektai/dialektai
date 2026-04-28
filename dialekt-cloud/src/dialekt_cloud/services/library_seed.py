"""Library catalog seeder.

The v1 curation pipeline is git-tracked: edit `LIBRARY_TEMPLATES`,
re-deploy, the cloud does an idempotent upsert into `library_entries`
on startup. v2 will move authoring to a founder admin UI but that's
deferred until manual curation hits a real bottleneck (mentor call).

Each template's manifest is the single source of truth for the agent's
behavior; category + tags here are the curation surface for the
catalog. requires_connection / requires_mcp are derived from the
manifest at seed time so the listing endpoint can filter without
parsing every YAML.

NO `pilot_source` / `installed_count` / `verified` / `complexity` /
`setup_time_minutes` columns — see the architectural review for why
each was rejected for v1. NO client / pilot identifiers in agent
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
from pathlib import Path

logger = logging.getLogger(__name__)


# IBA agent manifests live in the dialekt monorepo at agents/iba/.
# We load them at module import time so the library seeder ships
# the same YAML the agents/ directory carries — single source of
# truth, no risk of the library catalog drifting from the on-disk
# templates.
#
# When dialekt-cloud is built standalone (not from the monorepo),
# the loader falls back to a stub message that the operator can't
# install — better than silently shipping a stale copy. In production
# the deployment script copies agents/iba/ into the cloud image.

_REPO_ROOT = Path(__file__).resolve().parents[4]
_IBA_DIR = _REPO_ROOT / "agents" / "iba"


def _load_iba(name: str, *, setup_note: str | None = None) -> str:
    """Read agents/iba/{name}.yaml; optionally augment description
    with a "🔧 Setup needed" block so operators see required data
    in the Library card before installing."""
    path = _IBA_DIR / f"{name}.yaml"
    if not path.exists():
        # dialekt-cloud built without the monorepo — emit a placeholder
        # that fails closed (validator rejects empty system_prompt).
        logger.warning("IBA manifest missing at %s; library entry stubbed", path)
        return _yaml(f"""
            spec_version: "1.1.0"
            minimum_dialekt_version: "1.0.0"
            metadata:
              id: "00000000-0000-0000-0000-000000000000"
              name: "[STUB] {name}"
              description: "Manifest not bundled with this dialekt-cloud build."
              version: "0.0.0"
              language: "ru"
              author: {{name: "dias.now", email: "hello@dias.now"}}
              created_at: "2026-04-28T00:00:00+00:00"
              updated_at: "2026-04-28T00:00:00+00:00"
            model:
              preferred: "gemma3:12b"
              acceptable: []
              min_context_window: 8192
              requirements: {{min_ram_gb: 8, min_vram_gb: 4, recommended_ram_gb: 16}}
              parameters: {{temperature: 0.5, top_p: 0.9, max_tokens: 2048}}
            system_prompt: "Stub manifest — not installable."
            capabilities: {{groups: [], exceptions: []}}
            autonomy: {{recommended: "review-only", max_allowed: "review-only"}}
            input: {{type: "chat", placeholder: ""}}
            output: {{format: "markdown", streaming: false, destination: {{type: "notification"}}}}
            trigger: {{type: "interactive"}}
        """)

    raw = path.read_text(encoding="utf-8")
    if setup_note:
        # Inject the setup note into the metadata.description field.
        # We do a targeted replace instead of YAML parse-and-rewrite —
        # keeps the rest of the manifest byte-identical (signatures
        # downstream stay stable for non-IBA templates).
        import re
        pattern = re.compile(r'(  description:\s*")([^"]*)(")')
        m = pattern.search(raw)
        if m:
            current_desc = m.group(2)
            combined = f"{current_desc} 🔧 Setup: {setup_note}"
            raw = raw.replace(m.group(0), f'{m.group(1)}{combined}{m.group(3)}', 1)
    return raw


@dataclass(frozen=True)
class LibraryTemplate:
    id: str            # stable slug, used as primary key
    category: str
    tags: tuple[str, ...]
    manifest_yaml: str
    version: str = "1.0.0"


def _yaml(s: str) -> str:
    return textwrap.dedent(s).lstrip("\n")


# Each manifest below conforms to the dialekt-manifest spec_version 1.1.0.
# Required fields enumerated from the validator: metadata
# (id UUIDv4 / created_at / updated_at), model.requirements
# (min_ram_gb / min_vram_gb / recommended_ram_gb), model.parameters
# (temperature / top_p / max_tokens), capabilities, autonomy, input,
# output, trigger.
#
# UUIDs below were generated once with `uuid.uuid4()` and pinned —
# stable IDs let an installed agent know it shares lineage with the
# library entry even after rename.

_TS = "2026-04-27T00:00:00+00:00"


def _sql_manifest(*, uid: str, name: str, dialect: str, conn_type: str,
                  desc_extra: str = "") -> str:
    return _yaml(f"""
        spec_version: "1.1.0"
        minimum_dialekt_version: "1.0.0"
        metadata:
          id: "{uid}"
          name: "{name}"
          description: "Read-only {dialect} SQL assistant. Shows queries before executing.{(' ' + desc_extra) if desc_extra else ''}"
          version: "1.0.0"
          language: multi
          author:
            name: "dias.now"
            email: "hello@dias.now"
          created_at: "{_TS}"
          updated_at: "{_TS}"
        model:
          preferred: "qwen2.5-coder:7b"
          acceptable: ["qwen2.5-coder:14b", "gemma3:12b", "mistral:7b"]
          min_context_window: 16384
          requirements:
            min_ram_gb: 8
            min_vram_gb: 4
            recommended_ram_gb: 16
          parameters:
            temperature: 0.1
            top_p: 0.95
            max_tokens: 4096
        system_prompt: |
          You are a read-only {dialect} SQL assistant.
          Connection ID: {{{{connection_id}}}}
          Respond in the same language as the user (Russian or English).
          NEVER execute destructive SQL. ALWAYS show the query before executing.
          Format results as markdown tables. Add LIMIT for queries that may
          return >10k rows. Ask a clarifying question instead of guessing.
        variables:
          connection_id:
            type: string
            required: true
            description: "dialekt connection ID for the {dialect} database"
        capabilities:
          groups:
            - database_read
            - network
          exceptions: []
        connections:
          required:
            - type: {conn_type}
              role: "readonly"
              required_permissions: [SELECT]
        autonomy:
          recommended: "ask-before-write"
          max_allowed: "ask-before-write"
        input:
          type: "chat"
          placeholder: "Спросите о данных / Ask about your data..."
        output:
          format: "table"
          streaming: true
          destination:
            type: "notification"
        trigger:
          type: "interactive"
    """)


_PYTHON_REVIEWER = _yaml("""
    spec_version: "1.1.0"
    minimum_dialekt_version: "1.0.0"
    metadata:
      id: "5b7a2c1e-9d3f-4a52-b811-77a8e9f1b223"
      name: "Python Code Reviewer"
      description: "Reviews Python code for bugs, style, and idiomatic patterns. Read-only — never edits files."
      version: "1.0.0"
      language: multi
      author:
        name: "dias.now"
        email: "hello@dias.now"
      created_at: "2026-04-27T00:00:00+00:00"
      updated_at: "2026-04-27T00:00:00+00:00"
    model:
      preferred: "qwen2.5-coder:7b"
      acceptable: ["qwen2.5-coder:14b", "gemma3:12b"]
      min_context_window: 16384
      requirements:
        min_ram_gb: 8
        min_vram_gb: 4
        recommended_ram_gb: 16
      parameters:
        temperature: 0.2
        top_p: 0.95
        max_tokens: 4096
    system_prompt: |
      You are a senior Python code reviewer.
      Respond in the same language as the user (Russian or English).
      Identify bugs first, then style/idiom issues. Suggest concrete refactors
      with rewritten snippets. Read files via the filesystem tool — never edit.
    capabilities:
      groups:
        - filesystem_read
      exceptions: []
    autonomy:
      recommended: "review-only"
      max_allowed: "ask-before-write"
    input:
      type: "chat"
      placeholder: "Paste code or ask about a file..."
    output:
      format: "markdown"
      streaming: true
      destination:
        type: "notification"
    trigger:
      type: "interactive"
""")


_BASH_HELPER = _yaml("""
    spec_version: "1.1.0"
    minimum_dialekt_version: "1.0.0"
    metadata:
      id: "3c1d4f02-86b5-4e6a-9c51-12d4892ab7f8"
      name: "Bash Helper"
      description: "Suggests safe shell commands. Review-only autonomy — every command shown before running."
      version: "1.0.0"
      language: multi
      author:
        name: "dias.now"
        email: "hello@dias.now"
      created_at: "2026-04-27T00:00:00+00:00"
      updated_at: "2026-04-27T00:00:00+00:00"
    model:
      preferred: "qwen2.5-coder:7b"
      acceptable: ["qwen2.5-coder:14b", "gemma3:12b"]
      min_context_window: 8192
      requirements:
        min_ram_gb: 8
        min_vram_gb: 4
        recommended_ram_gb: 16
      parameters:
        temperature: 0.2
        top_p: 0.95
        max_tokens: 2048
    system_prompt: |
      You are a Bash / Linux command-line assistant.
      ALWAYS show the command BEFORE running. Refuse destructive ops on first
      try (rm -rf, dd, mkfs, force-push, drop database) — explain and confirm.
      Prefer composed POSIX pipelines. Show dry-run flags when supported.
    capabilities:
      groups:
        - shell_review_only
      exceptions: []
    autonomy:
      recommended: "review-only"
      max_allowed: "review-only"
    input:
      type: "chat"
      placeholder: "Describe what you want to do..."
    output:
      format: "markdown"
      streaming: true
      destination:
        type: "notification"
    trigger:
      type: "interactive"
""")


_DOC_SUMMARIZER = _yaml("""
    spec_version: "1.1.0"
    minimum_dialekt_version: "1.0.0"
    metadata:
      id: "8e29c44a-1b76-4310-a9d2-6f81c2ee4561"
      name: "Document Summarizer"
      description: "Three-bullet extractive summary of pasted text or local documents. No connections, no setup."
      version: "1.0.0"
      language: multi
      author:
        name: "dias.now"
        email: "hello@dias.now"
      created_at: "2026-04-27T00:00:00+00:00"
      updated_at: "2026-04-27T00:00:00+00:00"
    model:
      preferred: "gemma3:12b"
      acceptable: ["qwen2.5:7b", "mistral:7b"]
      min_context_window: 16384
      requirements:
        min_ram_gb: 8
        min_vram_gb: 4
        recommended_ram_gb: 16
      parameters:
        temperature: 0.3
        top_p: 0.95
        max_tokens: 1024
    system_prompt: |
      You are a document summarizer.
      Output exactly three bullets, one sentence each: main claim, strongest
      support, most important caveat. Never preamble — start with "•".
      Match the document's language.
    capabilities:
      groups:
        - filesystem_read
      exceptions: []
    autonomy:
      recommended: "review-only"
      max_allowed: "ask-before-write"
    input:
      type: "chat"
      placeholder: "Paste a document or ask to summarize a file..."
    output:
      format: "markdown"
      streaming: true
      destination:
        type: "notification"
    trigger:
      type: "interactive"
""")


_TRANSLATOR_RU_EN = _yaml("""
    spec_version: "1.1.0"
    minimum_dialekt_version: "1.0.0"
    metadata:
      id: "a4f6b98d-2c11-4855-be0e-9c5071a3d6f7"
      name: "RU/EN Translator"
      description: "Bidirectional Russian ↔ English translation. Preserves formatting, technical terms, and tone."
      version: "1.0.0"
      language: multi
      author:
        name: "dias.now"
        email: "hello@dias.now"
      created_at: "2026-04-27T00:00:00+00:00"
      updated_at: "2026-04-27T00:00:00+00:00"
    model:
      preferred: "gemma3:12b"
      acceptable: ["qwen2.5:7b", "mistral:7b"]
      min_context_window: 16384
      requirements:
        min_ram_gb: 8
        min_vram_gb: 4
        recommended_ram_gb: 16
      parameters:
        temperature: 0.2
        top_p: 0.95
        max_tokens: 4096
    system_prompt: |
      You are a Russian ↔ English translator.
      Detect the source language and translate to the other. Preserve markdown
      formatting; do not translate code inside fenced blocks; keep technical
      terms (API, SDK, JSON) as-is. Output the translation only, no preamble.
    capabilities:
      groups: []
      exceptions: []
    autonomy:
      recommended: "review-only"
      max_allowed: "review-only"
    input:
      type: "chat"
      placeholder: "Paste text to translate..."
    output:
      format: "markdown"
      streaming: true
      destination:
        type: "notification"
    trigger:
      type: "interactive"
""")


LIBRARY_TEMPLATES: tuple[LibraryTemplate, ...] = (
    LibraryTemplate(
        id="sql-analyst-postgres",
        category="data-analytics",
        tags=("sql", "postgresql", "analytics"),
        manifest_yaml=_sql_manifest(
            uid="d7c1a201-3b54-4f12-9d8a-1112233445aa",
            name="SQL Analyst (PostgreSQL)",
            dialect="PostgreSQL", conn_type="postgres",
        ),
    ),
    LibraryTemplate(
        id="sql-analyst-mysql",
        category="data-analytics",
        tags=("sql", "mysql", "analytics"),
        manifest_yaml=_sql_manifest(
            uid="d7c1a201-3b54-4f12-9d8a-1112233445bb",
            name="SQL Analyst (MySQL)",
            dialect="MySQL", conn_type="mysql",
        ),
    ),
    LibraryTemplate(
        id="sql-analyst-clickhouse",
        category="data-analytics",
        tags=("sql", "clickhouse", "analytics", "events"),
        manifest_yaml=_sql_manifest(
            uid="d7c1a201-3b54-4f12-9d8a-1112233445cc",
            name="SQL Analyst (ClickHouse)",
            dialect="ClickHouse", conn_type="clickhouse",
            desc_extra="Optimised for event-stream analytics.",
        ),
    ),
    LibraryTemplate(
        id="python-code-reviewer",
        category="development",
        tags=("python", "code-review", "linting"),
        manifest_yaml=_PYTHON_REVIEWER,
    ),
    LibraryTemplate(
        id="bash-helper",
        category="development",
        tags=("bash", "shell", "linux"),
        manifest_yaml=_BASH_HELPER,
    ),
    LibraryTemplate(
        id="document-summarizer",
        category="documents",
        tags=("summary", "documents", "reading"),
        manifest_yaml=_DOC_SUMMARIZER,
    ),
    LibraryTemplate(
        id="translator-ru-en",
        category="documents",
        tags=("translation", "russian", "english"),
        manifest_yaml=_TRANSLATOR_RU_EN,
    ),

    # ── IBA agent set ─────────────────────────────────────────────────
    # Education / business-school workflow stack. All Russian-first.
    # Setup notes injected into descriptions so operators see what
    # data they must provide BEFORE clicking Install. The wizard's
    # "needs N secrets" badge already covers credentials; the notes
    # below cover workspace files (programs.yaml, audit_targets.yaml,
    # bitrix_schema.yaml) that secrets_required[] can't express.

    LibraryTemplate(
        id="iba-content-editor",
        category="content",
        tags=("iba", "copywriting", "russian", "editing"),
        manifest_yaml=_load_iba(
            "content_editor",
            setup_note=(
                "Никаких внешних доступов не требуется — оператор "
                "вставляет сырое резюме / описание программы в чат, "
                "агент возвращает оформленный под IBA текст. "
                "Опционально: workspace для сохранения готовых "
                "текстов в {workspace}/resumes/ и {workspace}/programs/."
            ),
        ),
    ),

    LibraryTemplate(
        id="iba-smm-manager",
        category="marketing",
        tags=("iba", "instagram", "smm", "russian", "publishing"),
        manifest_yaml=_load_iba(
            "smm_manager",
            setup_note=(
                "Для copy-only режима (только тексты А/Б) — без "
                "настройки. Для AUTO-PUBLISH в Instagram нужны 7 "
                "секретов: instagram_access_token, instagram_ig_user_id "
                "(Facebook Developer App клиента), cdn_endpoint_url, "
                "cdn_access_key_id, cdn_secret_key, cdn_bucket, "
                "cdn_public_base (S3-compatible bucket — AWS S3 / R2 / "
                "B2 / MinIO). Опционально: подключённый Replicate MCP "
                "сервер для AI-картинок."
            ),
        ),
    ),

    LibraryTemplate(
        id="iba-program-scheduler",
        category="operations",
        tags=("iba", "scheduling", "russian", "calendar"),
        manifest_yaml=_load_iba(
            "program_scheduler",
            setup_note=(
                "Положите в {workspace}/programs.yaml каталог программ "
                "(пример смотри в agents/iba/example_catalog.yaml). "
                "Required fields на каждую программу: id, name. "
                "Optional: block (для антикластеринга), duration_days, "
                "format. CSV / JSON тоже принимаются. Без файла агент "
                "ничего не запланирует."
            ),
        ),
    ),

    LibraryTemplate(
        id="iba-website-audit",
        category="operations",
        tags=("iba", "audit", "seo", "content", "scheduled", "russian"),
        manifest_yaml=_load_iba(
            "website_audit",
            setup_note=(
                "Положите в {workspace}/audit_targets.yaml список URL "
                "под ключом ``urls:``. Агент обходит каждый через "
                "Playwright и сохраняет еженедельный отчёт в "
                "{workspace}/reports/audit-{date}.md. "
                "Запускается scheduled MON 8:00 Almaty. Без файла "
                "URLов агент скажет «положите файл» и не запустит crawl."
            ),
        ),
    ),

    LibraryTemplate(
        id="iba-cms-sync",
        category="operations",
        tags=("iba", "bitrix", "cms", "russian"),
        manifest_yaml=_load_iba(
            "cms_sync",
            setup_note=(
                "Требуется секрет bitrix_webhook_url — incoming webhook "
                "Bitrix24 портала клиента с правами на info-блоки. "
                "Дополнительно: положите {workspace}/bitrix_schema.yaml "
                "с IBLOCK_IDs и маппингом полей (см. шаблон в "
                "system_prompt). Без схемы агент работает в DRY-RUN "
                "режиме — показывает payload, но ничего не отправляет."
            ),
        ),
    ),

    LibraryTemplate(
        id="iba-law-monitor",
        category="research",
        tags=("iba", "legal", "kazakhstan", "scheduled", "russian"),
        manifest_yaml=_load_iba(
            "law_monitor",
            setup_note=(
                "Запускается scheduled FRI 18:00 Almaty. RSS-источник "
                "adilet.zan.kz привязан к манифесту — отдельной "
                "настройки не требует. Доставка через Telegram: нужен "
                "секрет iba_telegram_chat_id (chat_id куда уходит "
                "отчёт) + telegram_bot_token (бот клиента). Опционально "
                "переключите output.destination.type на 'email' и "
                "пропишите SMTP-секреты."
            ),
        ),
    ),

    LibraryTemplate(
        id="iba-legal-analyst",
        category="research",
        tags=("iba", "legal", "kazakhstan", "russian"),
        manifest_yaml=_load_iba(
            "legal_analyst",
            setup_note=(
                "Никаких внешних доступов. Интерактивный — оператор "
                "присылает текст НПА или вопрос «какие тренинги "
                "адаптировать под этот закон», агент отвечает. "
                "Использует web_search (Tavily) для проверки контекста "
                "если он включён в Settings."
            ),
        ),
    ),

    LibraryTemplate(
        id="iba-reminder-3days",
        category="marketing",
        tags=("iba", "instagram", "scheduled", "russian", "reminder"),
        manifest_yaml=_load_iba(
            "reminder_3days",
            setup_note=(
                "Запускается scheduled DAILY 10:00 Almaty. Проверяет "
                "расписание программ; если программа стартует через 3 "
                "дня — пишет напоминание-стори для Instagram. По "
                "умолчанию текст уходит оператору в Telegram (нужен "
                "iba_telegram_chat_id + telegram_bot_token). Для "
                "автопубликации — те же 7 IG/CDN секретов что у "
                "smm_manager."
            ),
        ),
    ),

    LibraryTemplate(
        id="iba-weekly-announcement",
        category="marketing",
        tags=("iba", "instagram", "scheduled", "russian", "announcement"),
        manifest_yaml=_load_iba(
            "weekly_announcement",
            setup_note=(
                "Запускается scheduled MON 09:00 Almaty. Анонсирует "
                "программы недели. Те же варианты доставки и автопоста "
                "что у reminder-3days."
            ),
        ),
    ),

    LibraryTemplate(
        id="iba-schedule-planner",
        category="operations",
        tags=("iba", "scheduling", "russian", "interactive"),
        manifest_yaml=_load_iba(
            "schedule_planner",
            setup_note=(
                "Старая версия планировщика — оперативный chat-режим "
                "для ad-hoc диапазонов. Захардкоженные праздники РК в "
                "system_prompt — обновляйте перед каждым новым годом. "
                "Для bulk-yearly расчёта 300 программ используйте "
                "iba-program-scheduler — он подключён к solver + "
                "kz_holidays и не требует обновления списка вручную."
            ),
        ),
    ),
)


def compute_signature(manifest_yaml: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        manifest_yaml.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _derive_flags(manifest_yaml: str) -> tuple[bool, bool]:
    requires_connection = "connections:" in manifest_yaml and (
        "required:" in manifest_yaml.split("connections:", 1)[1][:200]
        if "connections:" in manifest_yaml else False
    )
    requires_mcp = "mcp_tools" in manifest_yaml or "mcp_servers:" in manifest_yaml
    return requires_connection, requires_mcp


async def seed_library_entries(pool) -> int:
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
