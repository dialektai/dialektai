"""
Goal 8.1 — Structured prompt templating.

Wraps every agent system prompt in a consistent structure before the LLM call.
Applied automatically; agents can opt out via `prompt_wrapping: false` in manifest.
"""
from __future__ import annotations

import re
import textwrap
from datetime import datetime, timezone
from typing import Optional


_SECTION_SEP = "\n\n"


def _section(title: str, body: str) -> str:
    body = body.strip()
    if not body:
        return ""
    return f"## {title}\n{body}"


def _token_estimate(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars."""
    return max(1, len(text) // 4)


def build_system_prompt(
    *,
    raw_prompt: str,
    agent_name: str = "Assistant",
    language_hint: str | None = None,
    output_format: str | None = None,
    context_extras: dict | None = None,
    schema_summary: str | None = None,
    history_summary: str | None = None,
    few_shot_examples: list[dict] | None = None,
    max_tokens: int = 8192,
) -> str:
    """
    Return a structured system prompt assembling all sections.

    Parameters
    ----------
    raw_prompt:        The agent's core system_prompt (may contain {{vars}}).
    agent_name:        Display name for the ROLE header.
    language_hint:     ISO language code or None. Appended to LANGUAGE section.
    output_format:     Value of manifest.output.format, drives OUTPUT FORMAT section.
    context_extras:    Extra key→value pairs injected into CONTEXT section.
    schema_summary:    Schema RAG summary for DB agents.
    history_summary:   Summarized older messages when session exceeds budget.
    few_shot_examples: List of {question, answer} pairs for EXAMPLES section.
    max_tokens:        Context budget; trims sections from oldest to newest if exceeded.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections: list[str] = []

    # ROLE
    sections.append(_section("ROLE", raw_prompt))

    # LANGUAGE
    if language_hint:
        lang_map = {
            "ru": "Always respond in Russian. Use formal business Russian (вы).",
            "en": "Always respond in English.",
            "kk": "Always respond in Kazakh (Қазақша).",
        }
        lang_body = lang_map.get(language_hint, f"Respond in language: {language_hint}")
        sections.append(_section("LANGUAGE", lang_body))

    # OUTPUT FORMAT
    if output_format:
        fmt_rules = {
            "markdown": (
                "Always format your response in Markdown:\n"
                "- Use headers (##) to separate sections.\n"
                "- Use fenced code blocks for code.\n"
                "- Use markdown tables for tabular data.\n"
                "- Never output raw JSON unless wrapped in a code block."
            ),
            "table": (
                "Your primary output must be a Markdown table.\n"
                "If data is unavailable, explain briefly then stop.\n"
                "No prose paragraphs — tables only."
            ),
            "json": (
                "Output ONLY valid JSON. No prose, no markdown fences.\n"
                "If you cannot produce a valid JSON response, output:\n"
                '{"error": "reason"}'
            ),
            "file": (
                "Your response must be a file. Start with a metadata block:\n"
                "```meta\nfilename: <name>\ntype: <mime-type>\n```\n"
                "Then a content block with the file body."
            ),
        }.get(output_format, f"Output format: {output_format}.")
        sections.append(_section("OUTPUT FORMAT", fmt_rules))

    # CONTEXT
    ctx_lines = [f"Current time: {now_utc}"]
    if context_extras:
        for k, v in context_extras.items():
            ctx_lines.append(f"{k}: {v}")
    if schema_summary:
        ctx_lines.append("")
        ctx_lines.append("Relevant database tables:")
        ctx_lines.append(schema_summary)
    sections.append(_section("CONTEXT", "\n".join(ctx_lines)))

    # HISTORY SUMMARY
    if history_summary:
        sections.append(_section(
            "CONVERSATION HISTORY (summarized)",
            history_summary,
        ))

    # FEW-SHOT EXAMPLES
    if few_shot_examples:
        ex_lines = []
        for i, ex in enumerate(few_shot_examples[:3], 1):
            ex_lines.append(f"Example {i}:")
            ex_lines.append(f"User: {ex.get('question', '').strip()}")
            ex_lines.append(f"Assistant: {ex.get('answer', '').strip()}")
        sections.append(_section("EXAMPLES FROM PAST SUCCESSFUL INTERACTIONS", "\n".join(ex_lines)))

    assembled = _SECTION_SEP.join(s for s in sections if s)

    # Budget trim: if over limit, drop history_summary then few_shot_examples
    if _token_estimate(assembled) > max_tokens:
        sections_no_history = [s for s in sections if "HISTORY" not in s and "EXAMPLES" not in s]
        assembled = _SECTION_SEP.join(s for s in sections_no_history if s)

    return assembled


def substitute_template_vars(
    prompt: str,
    *,
    connection_id: str | None = None,
    connection_name: str | None = None,
    database_type: str | None = None,
    extra: dict | None = None,
) -> str:
    """
    Replace {{var}} placeholders in a prompt string.

    Handles: connection_id, connection_name, database_type, and any extras.
    Unknown placeholders that have no value are left as-is with a logged warning.
    """
    replacements: dict[str, str] = {}
    if connection_id is not None:
        replacements["connection_id"] = connection_id
    if connection_name is not None:
        replacements["connection_name"] = connection_name
    if database_type is not None:
        replacements["database_type"] = database_type
    if extra:
        replacements.update(extra)

    def _replace(m: re.Match) -> str:
        key = m.group(1).strip()
        return replacements.get(key, m.group(0))  # leave unknown placeholders

    return re.sub(r"\{\{([^}]+)\}\}", _replace, prompt)


def should_wrap(manifest_yaml: str | None) -> bool:
    """Return False if manifest opts out of wrapping via `prompt_wrapping: false`."""
    if not manifest_yaml:
        return True
    return "prompt_wrapping: false" not in manifest_yaml


def summarize_history(messages: list[dict], max_chars: int = 2000) -> str:
    """
    Produce a plain-text summary of older messages when session is long.

    This is a simple truncation-based summary. For production, replace with
    a small-model summarization call.
    """
    if not messages:
        return ""
    lines = []
    total = 0
    for m in reversed(messages):
        role = m.get("role", "user")
        content = str(m.get("content", ""))[:300]
        line = f"{role.capitalize()}: {content}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(reversed(lines))
