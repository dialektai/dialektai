"""Tests for dialekt/llm/prompt_wrapper.py (Goal 8.1)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from dialekt.llm.prompt_wrapper import (
    build_system_prompt,
    substitute_template_vars,
    should_wrap,
    summarize_history,
    _token_estimate,
)


# ── substitute_template_vars ──────────────────────────────────────────────────

def test_substitutes_connection_id():
    prompt = "BASE = 'http://localhost:8765'\nCONN = '{{connection_id}}'"
    result = substitute_template_vars(prompt, connection_id="abc-123")
    assert "abc-123" in result
    assert "{{connection_id}}" not in result


def test_substitutes_all_vars():
    prompt = "conn={{connection_id}} name={{connection_name}} type={{database_type}}"
    result = substitute_template_vars(
        prompt,
        connection_id="c1", connection_name="prod_db", database_type="postgres",
    )
    assert "c1" in result
    assert "prod_db" in result
    assert "postgres" in result
    assert "{{" not in result


def test_leaves_unknown_placeholders_intact():
    prompt = "{{unknown_var}} is here"
    result = substitute_template_vars(prompt)
    assert "{{unknown_var}}" in result


def test_extra_vars_substituted():
    prompt = "Hello {{user_name}}"
    result = substitute_template_vars(prompt, extra={"user_name": "Alice"})
    assert "Alice" in result


def test_none_values_not_substituted():
    prompt = "{{connection_id}} is empty"
    result = substitute_template_vars(prompt, connection_id=None)
    assert "{{connection_id}}" in result


# ── build_system_prompt ───────────────────────────────────────────────────────

def test_role_section_present():
    result = build_system_prompt(raw_prompt="You are a helpful assistant.")
    assert "## ROLE" in result
    assert "You are a helpful assistant." in result


def test_language_section_added():
    result = build_system_prompt(raw_prompt="You help.", language_hint="ru")
    assert "## LANGUAGE" in result
    assert "Russian" in result


def test_language_en():
    result = build_system_prompt(raw_prompt="You help.", language_hint="en")
    assert "English" in result


def test_output_format_markdown():
    result = build_system_prompt(raw_prompt="You help.", output_format="markdown")
    assert "## OUTPUT FORMAT" in result
    assert "Markdown" in result


def test_output_format_json():
    result = build_system_prompt(raw_prompt="You help.", output_format="json")
    assert "OUTPUT FORMAT" in result
    assert "JSON" in result


def test_context_section_has_timestamp():
    result = build_system_prompt(raw_prompt="You help.")
    assert "## CONTEXT" in result
    assert "UTC" in result


def test_schema_summary_injected():
    result = build_system_prompt(
        raw_prompt="You help.",
        schema_summary="Table public.orders: id int, amount numeric",
    )
    assert "orders" in result


def test_context_extras_injected():
    result = build_system_prompt(
        raw_prompt="You help.",
        context_extras={"connection_name": "prod_db", "database_type": "postgres"},
    )
    assert "prod_db" in result
    assert "postgres" in result


def test_history_summary_section():
    result = build_system_prompt(
        raw_prompt="You help.",
        history_summary="User asked about orders, assistant explained.",
    )
    assert "HISTORY" in result
    assert "orders" in result


def test_few_shot_examples_section():
    examples = [
        {"question": "How many orders?", "answer": "SELECT COUNT(*) FROM orders;"},
    ]
    result = build_system_prompt(raw_prompt="You help.", few_shot_examples=examples)
    assert "EXAMPLES" in result
    assert "COUNT(*)" in result


def test_token_budget_trims_history():
    long_history = "x" * 10000
    result = build_system_prompt(
        raw_prompt="You help.",
        history_summary=long_history,
        few_shot_examples=[{"question": "q", "answer": "a"}],
        max_tokens=100,
    )
    # history and examples should be dropped when over budget
    assert "HISTORY" not in result
    assert "EXAMPLES" not in result


def test_no_language_no_section():
    result = build_system_prompt(raw_prompt="You help.")
    assert "## LANGUAGE" not in result


# ── should_wrap ───────────────────────────────────────────────────────────────

def test_should_wrap_default():
    assert should_wrap(None) is True
    assert should_wrap("") is True
    assert should_wrap("some: yaml") is True


def test_should_wrap_opt_out():
    assert should_wrap("prompt_wrapping: false") is False


def test_should_wrap_true_not_false():
    assert should_wrap("prompt_wrapping: true") is True


# ── summarize_history ─────────────────────────────────────────────────────────

def test_summarize_empty():
    assert summarize_history([]) == ""


def test_summarize_basic():
    msgs = [
        {"role": "user", "content": "How many rows in orders?"},
        {"role": "assistant", "content": "SELECT COUNT(*) FROM orders returns 1234."},
    ]
    result = summarize_history(msgs)
    assert "orders" in result
    assert len(result) > 0


def test_summarize_respects_max_chars():
    msgs = [{"role": "user", "content": "x" * 500} for _ in range(20)]
    result = summarize_history(msgs, max_chars=200)
    assert len(result) <= 250  # some tolerance for line endings


# ── token estimate ────────────────────────────────────────────────────────────

def test_token_estimate_positive():
    assert _token_estimate("hello world") > 0
    assert _token_estimate("") == 1  # never 0
    assert _token_estimate("a" * 400) == 100
