"""
SQL safety tests: DDL and DML are rejected, SELECT passes through.
Tests the safety checker directly (no database connection needed).
"""
import pytest
from fastapi import HTTPException

from mcp_servers.postgres_mcp import _check_sql_safety


def passes(sql: str) -> None:
    """Assert SQL is accepted (no exception)."""
    _check_sql_safety(sql)


def rejects(sql: str) -> None:
    """Assert SQL raises HTTPException 422."""
    with pytest.raises(HTTPException) as exc_info:
        _check_sql_safety(sql)
    assert exc_info.value.status_code == 422


# ── SELECT queries (must pass) ────────────────────────────────────────────────

def test_simple_select():
    passes("SELECT id, name FROM users")

def test_select_with_where():
    passes("SELECT * FROM orders WHERE status = 'active'")

def test_select_with_join():
    passes("SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id")

def test_select_with_subquery():
    passes("SELECT * FROM (SELECT id, name FROM clients WHERE active = true) sub")

def test_select_with_cte():
    passes("""
        WITH recent AS (SELECT id FROM orders WHERE created_at > now() - interval '7 days')
        SELECT * FROM recent
    """)

def test_select_with_window_function():
    passes("SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at) rn FROM orders")

def test_select_aggregate():
    passes("SELECT COUNT(*), SUM(amount) FROM transactions WHERE year = 2025")

def test_select_with_comments_stripped():
    # SQL with comments that contain DDL words — should still pass because they're in comments
    passes("""
        -- DROP TABLE users  (this is a comment, not a statement)
        SELECT id FROM users
    """)

def test_select_with_block_comment_ddl():
    passes("/* CREATE TABLE foo (id int) */ SELECT 1")


# ── DDL statements (must reject) ─────────────────────────────────────────────

def test_drop_table():
    rejects("DROP TABLE users")

def test_create_table():
    rejects("CREATE TABLE new_table (id INT)")

def test_alter_table():
    rejects("ALTER TABLE users ADD COLUMN email TEXT")

def test_truncate():
    rejects("TRUNCATE orders")

def test_create_index():
    rejects("CREATE INDEX idx ON users(email)")

def test_drop_database():
    rejects("DROP DATABASE production")

def test_grant():
    rejects("GRANT ALL ON TABLE users TO readonly_user")

def test_revoke():
    rejects("REVOKE SELECT ON TABLE secrets FROM attacker")

def test_vacuum():
    rejects("VACUUM ANALYZE users")

def test_reindex():
    rejects("REINDEX TABLE users")


# ── DML statements (must reject) ─────────────────────────────────────────────

def test_insert():
    rejects("INSERT INTO users (name) VALUES ('hacker')")

def test_update():
    rejects("UPDATE users SET admin = true WHERE id = 42")

def test_delete():
    rejects("DELETE FROM users WHERE id = 1")

def test_delete_all():
    rejects("DELETE FROM users")

def test_merge():
    rejects("MERGE INTO target USING source ON (target.id = source.id) WHEN MATCHED THEN UPDATE SET name = source.name")


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_case_insensitive_rejection():
    rejects("drop table users")
    rejects("Drop Table users")
    rejects("delete from orders")

def test_multiline_delete():
    rejects("""
        DELETE
        FROM
        customers
        WHERE id > 0
    """)

def test_sql_with_delete_in_column_name_alias():
    # 'delete_reason' as an alias should NOT trigger rejection
    # This is tricky — our regex uses word boundaries \b so 'delete_reason' won't match
    passes("SELECT delete_reason, created_at FROM moderation_log")

def test_table_named_insert():
    # A table literally named 'insert' should trigger because regex matches word boundary
    # This is a known limitation — acceptable trade-off for security
    # Just verify the current behavior is rejection (conservative)
    rejects('SELECT * FROM "insert"')  # word 'insert' present — rejected (conservative)

def test_set_role_rejected():
    rejects("SET ROLE admin")

def test_set_session_rejected():
    rejects("SET SESSION authorization postgres")
