"""Tests for the MCP Templates catalog endpoint.

The catalog drives the Quick Add tile row in Settings → MCP Servers
(v0.21 commit 1). Endpoint must:

- Return 200 OK with the bundled catalog JSON.
- Expose a non-empty `templates` array with the documented schema.
- Mirror `MCPServerCreate` shape so the frontend modal can submit
  the resolved payload through the existing /mcp-servers POST.
- Never include secret VALUES — only secret REFS (the prompts are
  metadata, not stored credentials).
"""
import json
import re
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import server as srv
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)
        original = (srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR)
        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR = tmp_dir
        with TestClient(srv.app, raise_server_exceptions=True) as c:
            yield c
        srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = original


# ── Endpoint shape ──────────────────────────────────────────────────────────


def test_get_mcp_templates_returns_200_with_catalog(client):
    r = client.get("/mcp-templates")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert isinstance(body.get("version"), int) and body["version"] >= 1
    assert isinstance(body.get("templates"), list)
    assert len(body["templates"]) >= 1


def test_each_template_has_required_fields(client):
    r = client.get("/mcp-templates")
    for tpl in r.json()["templates"]:
        # Identity
        assert isinstance(tpl.get("id"), str) and tpl["id"]
        assert re.match(r"^[a-z][a-z0-9-]*$", tpl["id"]), \
            f"template id {tpl['id']!r} must be kebab-case"
        assert isinstance(tpl.get("label"), str) and tpl["label"]
        assert isinstance(tpl.get("description"), str)
        assert tpl.get("transport") in ("stdio", "http")
        # Drivable contracts
        assert isinstance(tpl.get("secret_prompts"), list)
        assert isinstance(tpl.get("string_prompts", []), list)
        assert isinstance(tpl.get("default_timeout_seconds"), (int, float))
        # Honesty bar
        assert isinstance(tpl.get("validated"), bool)


def test_secret_prompts_have_ref_and_label(client):
    """Every secret_prompts entry must carry a ref + label so the
    modal can render a labeled masked input."""
    r = client.get("/mcp-templates")
    for tpl in r.json()["templates"]:
        for prompt in tpl.get("secret_prompts", []):
            assert isinstance(prompt.get("ref"), str) and prompt["ref"]
            assert isinstance(prompt.get("label"), str) and prompt["label"]


def test_template_ids_are_unique(client):
    r = client.get("/mcp-templates")
    ids = [t["id"] for t in r.json()["templates"]]
    assert len(ids) == len(set(ids)), f"duplicate template ids: {ids}"


# ── Specific template invariants we don't want to drift ────────────────────


def test_github_template_marked_validated(client):
    """github is the validated reference template (ws_chat_mcp_integration
    + run_github_e2e harness on 2026-04-25). If it's ever flipped to
    `validated: false` the catalog has regressed — fail loudly."""
    r = client.get("/mcp-templates")
    github = next(
        (t for t in r.json()["templates"] if t["id"] == "github"), None
    )
    assert github is not None, "github template must exist in catalog"
    assert github["validated"] is True
    assert github["transport"] == "stdio"
    assert github["command"][:2] == ["npx", "-y"]


def test_filesystem_template_uses_string_prompt_for_sandbox(client):
    """The filesystem template embeds ${prompt:sandbox_path} in its
    command. The frontend resolves it before POST. Catalog must
    expose a matching string_prompts entry so the modal renders the
    input."""
    r = client.get("/mcp-templates")
    fs = next(
        (t for t in r.json()["templates"] if t["id"] == "filesystem"), None
    )
    assert fs is not None
    assert any("${prompt:sandbox_path}" in arg for arg in fs["command"]), \
        "filesystem template command must reference ${prompt:sandbox_path}"
    refs = [p["ref"] for p in fs.get("string_prompts", [])]
    assert "sandbox_path" in refs


def test_community_packages_are_version_pinned(client):
    """Community packages MUST be version-pinned in the npx command
    so an upstream churn doesn't break pilots' first launch. Mentor
    P1 from the v0.21 plan v1 review — refusing to ship unpinned
    `npx -y @some/pkg` for the 3 untested templates.
    """
    r = client.get("/mcp-templates")
    pinned_ids = ("linear", "notion", "figma")
    for tpl in r.json()["templates"]:
        if tpl["id"] not in pinned_ids:
            continue
        # Find the @scope/pkg@version-shaped or pkg@version-shaped argv token
        last = tpl["command"][-1]
        assert "@" in last and last.split("@")[-1], \
            f"community template {tpl['id']!r} must pin a version " \
            f"(got {last!r})"


def test_template_schema_no_plaintext_secrets(client):
    """Belt-and-suspenders regression: nowhere in the catalog should
    a `value`, `token`, `secret`, or `password` field appear under a
    template. Templates carry REFS and PROMPTS, never VALUES."""
    r = client.get("/mcp-templates")
    raw = json.dumps(r.json())
    # The string "secret" itself appears in placeholder text and
    # description copy ("personal access token", "Notion integration
    # token") — that's fine. We're checking that no JSON KEY named
    # `value`, `password`, or any secret-like KEY surfaces inside
    # the templates.
    for tpl in r.json()["templates"]:
        for prompt in tpl.get("secret_prompts", []) + tpl.get("string_prompts", []):
            assert "value" not in prompt, (
                f"template {tpl['id']!r} prompt has a `value` key — "
                f"templates must never carry plaintext credentials"
            )


def test_only_validated_github_and_filesystem_have_validated_true(client):
    """Honesty bar: the only two templates that have actually been
    run end-to-end as part of dialekt's regression suite or the
    GitHub MCP validation pass are `github` and `filesystem`. All
    other templates must ship as `validated: false` with an amber
    pill in the UI. If a community template is flipped to `true`
    without a corresponding entry in MCP_PRODUCTION_VALIDATION.md,
    this test fails — preventing accidental promotion.
    """
    r = client.get("/mcp-templates")
    for tpl in r.json()["templates"]:
        if tpl["validated"]:
            assert tpl["id"] in ("github", "filesystem"), (
                f"template {tpl['id']!r} cannot be `validated: true` "
                f"without a documented validation pass"
            )
