"""Diagnostic E2E runner (2026-04-24 overnight sweep).

NOT a pytest file — runs standalone, collects JSON findings into
docs/OVERNIGHT_E2E_REPORT_2026-04-24.md via the accompanying writer.
Uses TestClient (not HTTP) so we don't pollute the user's live
~/.dialekt state, but hits the real FastAPI app for E2E fidelity.
"""
import json
import os
import sys
import tempfile
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))  # python/ for `import server`

# Make sure we're using the postgres integration DSN.
PG_HOST, PG_PORT = "localhost", 15432
PG_DB, PG_USER, PG_PASS = "dialekt_integration", "dialekt_test", "dialekt_test"

CH_HOST, CH_PORT = "localhost", 18123
CH_DB, CH_USER, CH_PASS = "dialekt_integration", "dialekt_test", "dialekt_test"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _base_manifest(**overrides) -> str:
    defaults = dict(
        uuid=str(uuid.uuid4()),
        name="E2E Diag Agent",
        description="extended E2E diagnostic agent",
        version="1.0.0",
        language="en",
        tags_yaml="[]",
        author_name="t",
        author_email="t@t.t",
        now=_now_iso(),
        model_preferred="llama3.2:3b",
        acceptable_yaml="[]",
        min_context_window=32768,
        min_ram_gb=8,
        min_vram_gb=0,
        recommended_ram_gb=16,
        temperature=0.7,
        top_p=0.95,
        max_tokens=4096,
        system_prompt="you are a test agent",
        capabilities_groups="[]",
        connections_block="",
        variables_block="",
        autonomy_recommended="ask-before-write",
        autonomy_max="ask-before-write",
        input_placeholder="Ask me anything...",
        output_format="markdown",
        streaming="true",
        trigger='trigger:\n  type: "interactive"',
    )
    defaults.update(overrides)
    return (
        'spec_version: "1.0.1"\n'
        'minimum_dialekt_version: "1.0.0"\n\n'
        'metadata:\n'
        f'  id: "{defaults["uuid"]}"\n'
        f'  name: "{defaults["name"]}"\n'
        f'  description: "{defaults["description"]}"\n'
        f'  version: "{defaults["version"]}"\n'
        f'  language: "{defaults["language"]}"\n'
        f'  tags: {defaults["tags_yaml"]}\n'
        f'  author:\n'
        f'    name: "{defaults["author_name"]}"\n'
        f'    email: "{defaults["author_email"]}"\n'
        f'  created_at: "{defaults["now"]}"\n'
        f'  updated_at: "{defaults["now"]}"\n\n'
        'model:\n'
        f'  preferred: "{defaults["model_preferred"]}"\n'
        f'  acceptable: {defaults["acceptable_yaml"]}\n'
        f'  min_context_window: {defaults["min_context_window"]}\n'
        '  requirements:\n'
        f'    min_ram_gb: {defaults["min_ram_gb"]}\n'
        f'    min_vram_gb: {defaults["min_vram_gb"]}\n'
        f'    recommended_ram_gb: {defaults["recommended_ram_gb"]}\n'
        '  parameters:\n'
        f'    temperature: {defaults["temperature"]}\n'
        f'    top_p: {defaults["top_p"]}\n'
        f'    max_tokens: {defaults["max_tokens"]}\n\n'
        'system_prompt: |\n'
        f'  {defaults["system_prompt"]}\n\n'
        'capabilities:\n'
        f'  groups: {defaults["capabilities_groups"]}\n'
        + (f'\n{defaults["variables_block"]}\n' if defaults["variables_block"] else "")
        + (f'\n{defaults["connections_block"]}\n' if defaults["connections_block"] else "")
        + '\nautonomy:\n'
        f'  recommended: "{defaults["autonomy_recommended"]}"\n'
        f'  max_allowed: "{defaults["autonomy_max"]}"\n\n'
        'input:\n  type: "chat"\n'
        f'  placeholder: "{defaults["input_placeholder"]}"\n\n'
        'output:\n'
        f'  format: "{defaults["output_format"]}"\n'
        f'  streaming: {defaults["streaming"]}\n'
        '  destination:\n    type: "notification"\n\n'
        f'{defaults["trigger"]}\n'
    )


def _conn_block(drivers):
    """Build `connections:` block for the given list of driver types."""
    rows = []
    for d in drivers:
        rows.append(
            f'    - type: "{d}"\n'
            '      role: "readonly"\n'
            f'      purpose: "E2E diag — {d}"\n'
        )
    return "connections:\n  required:\n" + "".join(rows)


def _vars_block(entries):
    """entries = [(name, type), ...]"""
    rows = []
    for n, t in entries:
        rows.append(
            f'  {n}:\n'
            f'    type: "{t}"\n'
            '    required: false\n'
            f'    description: "E2E {n} ({t})"\n'
        )
    return "variables:\n" + "".join(rows)


def _caps(groups):
    if not groups:
        return "[]"
    inner = "\n".join(f"    - {g}" for g in groups)
    return "\n" + inner


def make_client():
    """Returns a context manager yielding TestClient with temp DB."""
    from fastapi.testclient import TestClient
    import server as srv
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        tmp_dir = Path(tempfile.mkdtemp(prefix="dialekt-e2e-")) / ".dialekt"
        tmp_dir.mkdir(parents=True)
        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR = tmp_dir
        # Enter the TestClient context so FastAPI startup events fire
        # (that's what wires up the SQLite pool the MCP routers need).
        with TestClient(srv.app, raise_server_exceptions=False) as c:
            yield c

    return _cm()


# ── Results container ───────────────────────────────────────────────────────

class Results:
    def __init__(self):
        self.scenarios = []

    def record(self, group, name, status, detail, evidence=None):
        """status ∈ {'pass','fail','error','skip'}"""
        self.scenarios.append(
            dict(group=group, name=name, status=status, detail=detail, evidence=evidence or {})
        )
        sym = {"pass": "✓", "fail": "✗", "error": "!", "skip": "~"}.get(status, "?")
        print(f"  [{sym}] {group}/{name}: {status} — {detail[:120]}")

    def summary(self):
        out = dict(pass_=0, fail=0, error=0, skip=0)
        for s in self.scenarios:
            out[s["status"].replace("pass", "pass_")] += 1
        return out


# ── Test groups ─────────────────────────────────────────────────────────────

def run_wizard_scenarios(client, results: Results):
    print("\n[1/3] WIZARD PUBLISH (10 scenarios)")

    # 1. SQL Analyst with PostgreSQL
    y = _base_manifest(
        name="SQL Analyst PG",
        system_prompt="SQL analyst with PostgreSQL access",
        capabilities_groups=_caps(["database_read"]),
        connections_block=_conn_block(["postgres"]),
    )
    _publish_and_record(client, results, "wizard", "01-sql-analyst-postgres", y)

    # 2. SQL Analyst with MySQL
    y = _base_manifest(
        name="SQL Analyst MySQL",
        capabilities_groups=_caps(["database_read"]),
        connections_block=_conn_block(["mysql"]),
    )
    _publish_and_record(client, results, "wizard", "02-sql-analyst-mysql", y)

    # 3. SQL Analyst with ClickHouse
    y = _base_manifest(
        name="SQL Analyst CH",
        capabilities_groups=_caps(["database_read"]),
        connections_block=_conn_block(["clickhouse"]),
    )
    _publish_and_record(client, results, "wizard", "03-sql-analyst-clickhouse", y)

    # 4. Pure LLM without DB, autonomy=manual
    y = _base_manifest(
        name="Pure LLM manual",
        autonomy_recommended="manual",
        autonomy_max="manual",
    )
    _publish_and_record(client, results, "wizard", "04-pure-llm-manual", y)

    # 5. Pure LLM, autonomy=autonomous
    y = _base_manifest(
        name="Pure LLM autonomous",
        autonomy_recommended="autonomous",
        autonomy_max="autonomous",
    )
    _publish_and_record(client, results, "wizard", "05-pure-llm-autonomous", y)

    # 6. Pure LLM, autonomy=review-only
    y = _base_manifest(
        name="Pure LLM review-only",
        autonomy_recommended="review-only",
        autonomy_max="review-only",
    )
    _publish_and_record(client, results, "wizard", "06-pure-llm-review-only", y)

    # 7. Power user with all 6 capabilities
    all_caps = [
        "filesystem_read", "network", "browser",
        "database_read", "shell_execute", "screen_capture",
    ]
    y = _base_manifest(
        name="Power User all-caps",
        capabilities_groups=_caps(all_caps),
        connections_block=_conn_block(["postgres"]),
    )
    _publish_and_record(client, results, "wizard", "07-power-user-all-caps", y)

    # 8. Minimal agent (only required fields)
    y = _base_manifest(name="Minimal Agent")
    _publish_and_record(client, results, "wizard", "08-minimal-agent", y)

    # 9. Multi-DB agent (postgres + mysql required)
    y = _base_manifest(
        name="Multi-DB Agent",
        capabilities_groups=_caps(["database_read"]),
        connections_block=_conn_block(["postgres", "mysql"]),
    )
    _publish_and_record(client, results, "wizard", "09-multi-db-pg-mysql", y)

    # 10. Agent with 3 variables of different types
    y = _base_manifest(
        name="Vars-Agent",
        variables_block=_vars_block([
            ("API_KEY", "string"),
            ("MAX_ROWS", "number"),
            ("DRY_RUN", "boolean"),
        ]),
    )
    _publish_and_record(client, results, "wizard", "10-vars-mixed-types", y)


def _publish_and_record(client, results: Results, group, name, yaml_str):
    try:
        r = client.post("/agents/import-yaml", json={"manifest_yaml": yaml_str})
        ok = r.status_code == 201
        body = None
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text[:400]}
        if ok:
            # Sanity: can we read the agent back and is its manifest intact?
            agent_id = body.get("id")
            if agent_id:
                r2 = client.get(f"/agents/{agent_id}")
                if r2.status_code != 200:
                    results.record(group, name, "fail",
                                   f"import 201 but GET /agents/{{id}} returned {r2.status_code}",
                                   dict(status=r.status_code, body=body))
                    return
                # Clean up so we don't pollute subsequent counts.
                client.delete(f"/agents/{agent_id}")
            results.record(group, name, "pass",
                           f"HTTP {r.status_code}",
                           dict(status=r.status_code, agent_id=body.get("id")))
        else:
            results.record(group, name, "fail",
                           f"HTTP {r.status_code} — {str(body)[:200]}",
                           dict(status=r.status_code, body=body))
    except Exception as e:
        results.record(group, name, "error",
                       f"{type(e).__name__}: {e}",
                       dict(traceback=traceback.format_exc()[:500]))


def run_sql_scenarios(client, results: Results):
    print("\n[2/3] SQL EXECUTION (5 scenarios)")

    # Create a PG connection pointed at the integration container.
    try:
        r = client.post("/connections", json={
            "name": "e2e-diag-pg",
            "host": PG_HOST,
            "port": PG_PORT,
            "database": PG_DB,
            "username": PG_USER,
            "password": PG_PASS,
        })
        if r.status_code != 201:
            results.record("sql", "00-connection-create", "error",
                           f"cannot create PG conn: {r.status_code} {r.text[:200]}")
            for i in (1, 2, 3, 4, 5):
                results.record("sql", f"{i:02d}-skipped", "skip",
                               "no PG connection available")
            return
        conn_id = r.json()["id"]
    except Exception as e:
        results.record("sql", "00-connection-create", "error", f"{type(e).__name__}: {e}")
        return

    try:
        # Verify test reachability
        r = client.post(f"/connections/{conn_id}/test")
        if r.status_code != 200 or not r.json().get("ok"):
            results.record("sql", "00-connection-test", "fail",
                           f"POST /test returned {r.status_code}: {r.text[:200]}")
            for i in (1, 2, 3, 4, 5):
                results.record("sql", f"{i:02d}-skipped", "skip",
                               "PG connection unhealthy")
            return

        # 1. Simple COUNT
        _exec_sql(client, conn_id, results, "01-simple-count",
                  "SELECT COUNT(*) AS n FROM ecom.customers")

        # 2. JOIN across 2 tables
        _exec_sql(client, conn_id, results, "02-join-2-tables",
                  "SELECT c.country, COUNT(o.id) AS orders "
                  "FROM ecom.customers c JOIN ecom.orders o ON o.customer_id = c.id "
                  "GROUP BY c.country ORDER BY orders DESC LIMIT 5")

        # 3. GROUP BY with aggregations
        _exec_sql(client, conn_id, results, "03-group-by-aggs",
                  "SELECT status, COUNT(*) AS n, ROUND(AVG(total_usd)::numeric, 2) AS avg_total "
                  "FROM ecom.orders GROUP BY status ORDER BY n DESC")

        # 4. Invalid SQL (syntax error) — must surface error cleanly
        _exec_sql(client, conn_id, results, "04-invalid-syntax",
                  "SELEKT * FROM ecom.customers",
                  expect_error=True)

        # 5. Non-existent table
        _exec_sql(client, conn_id, results, "05-missing-table",
                  "SELECT * FROM ecom.nonexistent_zzz LIMIT 1",
                  expect_error=True)

    finally:
        client.delete(f"/connections/{conn_id}")


def _exec_sql(client, conn_id, results: Results, name, sql, expect_error=False):
    try:
        r = client.post(f"/connections/{conn_id}/query", json={"sql": sql})
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text[:400]}

        if expect_error:
            # Must surface an error (either non-2xx or ok:false or an error field)
            errored = (
                r.status_code >= 400
                or body.get("error")
                or body.get("ok") is False
                or (isinstance(body, dict) and body.get("detail"))
            )
            if errored:
                results.record("sql", name, "pass",
                               f"correctly surfaced error: HTTP {r.status_code} — "
                               f"{(body.get('error') or body.get('detail') or '…')[:120]}",
                               dict(status=r.status_code, body=body))
            else:
                results.record("sql", name, "fail",
                               f"expected error but got HTTP {r.status_code} ok body",
                               dict(status=r.status_code, body=body))
            return

        if r.status_code == 200 and isinstance(body, dict) and body.get("rows") is not None:
            rows = body["rows"]
            results.record("sql", name, "pass",
                           f"{len(rows)} rows returned",
                           dict(status=r.status_code, sample=rows[:3],
                                columns=body.get("columns")))
        else:
            results.record("sql", name, "fail",
                           f"HTTP {r.status_code} — {str(body)[:200]}",
                           dict(status=r.status_code, body=body))
    except Exception as e:
        results.record("sql", name, "error",
                       f"{type(e).__name__}: {e}",
                       dict(traceback=traceback.format_exc()[:500]))


def run_routing_scenarios(results: Results):
    print("\n[3/3] AGENT MODEL ROUTING (3 scenarios)")
    from server import pick_model_for_agent

    # Real installed models on this machine (from /health earlier):
    #   qwen2.5-coder:7b, gemma3-12b:latest, gemma2:2b, nomic-embed-text:v1.5
    installed = {"qwen2.5-coder:7b", "gemma3-12b:latest", "gemma2:2b"}
    default_model = "gemma3-12b"

    # 1. Agent with preferred model installed
    manifest = {"model": {"preferred": "qwen2.5-coder:7b", "acceptable": []}}
    picked = pick_model_for_agent(manifest, installed, default_model)
    if picked == "qwen2.5-coder:7b":
        results.record("routing", "01-preferred-installed", "pass",
                       f"picked {picked} (exact match)")
    else:
        results.record("routing", "01-preferred-installed", "fail",
                       f"expected qwen2.5-coder:7b, got {picked}")

    # 2. Preferred :32b, only :7b installed → family match
    manifest = {"model": {"preferred": "qwen2.5-coder:32b", "acceptable": []}}
    picked = pick_model_for_agent(manifest, installed, default_model)
    if picked == "qwen2.5-coder:7b":
        results.record("routing", "02-family-match-32b-to-7b", "pass",
                       f"picked {picked} (family match)")
    else:
        results.record("routing", "02-family-match-32b-to-7b", "fail",
                       f"expected qwen2.5-coder:7b, got {picked}")

    # 3. Agent without preferred → global default
    manifest = {"model": {"preferred": None, "acceptable": []}}
    picked = pick_model_for_agent(manifest, installed, default_model)
    if picked == default_model:
        results.record("routing", "03-no-preferred-use-default", "pass",
                       f"picked {picked} (global default)")
    else:
        results.record("routing", "03-no-preferred-use-default", "fail",
                       f"expected {default_model}, got {picked}")


# ── Entry point ─────────────────────────────────────────────────────────────

def run_all_scenarios() -> dict:
    """Execute every scenario group and return a structured results dict.

    Shape: {"scenarios": [...], "summary": {"pass_", "fail", "error", "skip"},
    "generated_at": iso-timestamp}. The pytest wrapper in
    test_e2e_integration.py asserts against this.
    """
    results = Results()
    with make_client() as client:
        run_wizard_scenarios(client, results)
        run_sql_scenarios(client, results)
        run_routing_scenarios(results)
    return dict(
        scenarios=results.scenarios,
        summary=results.summary(),
        generated_at=_now_iso(),
    )


def main():
    data = run_all_scenarios()

    # Emit machine-readable JSON for the writer to consume.
    out = HERE.parent / "e2e_diag_results.json"
    out.write_text(json.dumps(data, indent=2))
    s = data["summary"]
    print(f"\n== {s['pass_']} pass · {s['fail']} fail · {s['error']} error · {s['skip']} skip ==")
    print(f"Results JSON → {out}")


if __name__ == "__main__":
    main()
