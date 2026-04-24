"""Pytest wrapper around e2e_diag_runner.py (R3 from overnight report).

Skipped by default unless DIALEKT_RUN_E2E=1 is set, because it requires
a live PostgreSQL container (integration-postgres-1 on :15432) seeded
from tests/integration/seed/postgres_seed.sql.

In CI this runs inside .github/workflows/e2e-integration.yml which
spins up PG as a service, seeds it, then sets DIALEKT_RUN_E2E=1.

Locally:
    cd python/tests/integration && docker compose up -d --wait postgres
    cd ../.. && DIALEKT_RUN_E2E=1 pytest tests/test_e2e_integration.py -v
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("DIALEKT_RUN_E2E") != "1",
    reason="E2E tests require a live PG container — set DIALEKT_RUN_E2E=1 to enable",
)

# Import lazily inside the fixture so the whole file doesn't blow up
# if server/deps aren't installed in a no-E2E environment.


@pytest.fixture(scope="module")
def e2e_results():
    """Run all 18 E2E scenarios once per session and cache the dict."""
    from tests.e2e_diag_runner import run_all_scenarios
    return run_all_scenarios()


def test_wizard_scenarios_all_pass(e2e_results):
    wizard = [r for r in e2e_results["scenarios"] if r["group"] == "wizard"]
    assert len(wizard) == 10, f"expected 10 wizard scenarios, got {len(wizard)}"
    failures = [r for r in wizard if r["status"] != "pass"]
    assert not failures, (
        "Wizard scenarios failed:\n"
        + "\n".join(f"  - {r['name']}: {r['status']} — {r['detail']}" for r in failures)
    )


def test_sql_scenarios_all_pass(e2e_results):
    sql = [r for r in e2e_results["scenarios"] if r["group"] == "sql"]
    assert len(sql) == 5, f"expected 5 sql scenarios, got {len(sql)}"
    failures = [r for r in sql if r["status"] != "pass"]
    assert not failures, (
        "SQL scenarios failed:\n"
        + "\n".join(f"  - {r['name']}: {r['status']} — {r['detail']}" for r in failures)
    )


def test_routing_scenarios_all_pass(e2e_results):
    routing = [r for r in e2e_results["scenarios"] if r["group"] == "routing"]
    assert len(routing) == 3, f"expected 3 routing scenarios, got {len(routing)}"
    failures = [r for r in routing if r["status"] != "pass"]
    assert not failures, (
        "Routing scenarios failed:\n"
        + "\n".join(f"  - {r['name']}: {r['status']} — {r['detail']}" for r in failures)
    )


def test_no_failures_or_errors(e2e_results):
    s = e2e_results["summary"]
    assert s["fail"] == 0, f"{s['fail']} scenario(s) failed"
    assert s["error"] == 0, f"{s['error']} scenario(s) errored"
