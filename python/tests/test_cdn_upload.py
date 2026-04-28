"""Tests for ``dialekt.mcp.server.tools.cdn``.

Mocks both boto3 (no real AWS / R2 / B2 calls) and the keychain
(no OS-level secrets), so the suite runs offline and deterministic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools import cdn as cdn_tool
from dialekt.mcp.server.tools.cdn import register_cdn_tools


class _StubS3Client:
    """Mimics enough of boto3 S3 client to satisfy the tool path."""
    def __init__(self):
        self.calls: list[dict] = []
        self.put_error: Exception | None = None

    def put_object(self, **kwargs):
        if self.put_error:
            raise self.put_error
        self.calls.append(kwargs)
        return {"ETag": '"deadbeef"'}


@pytest.fixture
def stub_s3(monkeypatch):
    client = _StubS3Client()

    def _factory(endpoint_url, access_key_id, secret_key, region):
        client.factory_args = {
            "endpoint_url": endpoint_url,
            "access_key_id": access_key_id,
            "secret_key": secret_key,
            "region": region,
        }
        return client

    monkeypatch.setattr(cdn_tool, "_build_s3_client", _factory)
    return client


@pytest.fixture
def fake_secrets(monkeypatch):
    store: dict[str, str] = {}

    def _get(name):
        return store.get(name)

    monkeypatch.setattr(cdn_tool.secrets_module, "get_secret", _get)
    return store


def _build_server(allowed_roots):
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(allowed_file_roots=allowed_roots),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_cdn_tools(srv)
    return srv, events


def _seed_full_creds(fake_secrets):
    fake_secrets.update({
        "cdn_endpoint_url": "https://s3.example.com",
        "cdn_access_key_id": "AK",
        "cdn_secret_key": "SK",
        "cdn_bucket": "iba-media",
        "cdn_region": "auto",
        "cdn_public_base": "https://cdn.iba.kz/{key}",
    })


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_upload_uses_secrets(stub_s3, fake_secrets, tmp_path):
    _seed_full_creds(fake_secrets)
    image = tmp_path / "carousel" / "slide_01.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    out = tool(local_path=str(image))
    assert out.get("error") is not True
    assert out["url"].startswith("https://cdn.iba.kz/uploads/")
    assert out["url"].endswith("slide_01.png")
    assert out["bucket"] == "iba-media"
    assert out["content_type"] == "image/png"
    assert out["size_bytes"] > 0
    assert len(stub_s3.calls) == 1
    call = stub_s3.calls[0]
    assert call["Bucket"] == "iba-media"
    assert call["ContentType"] == "image/png"


def test_upload_inline_creds_override_keychain(stub_s3, fake_secrets, tmp_path):
    fake_secrets["cdn_endpoint_url"] = "https://wrong.example.com"
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    out = tool(
        local_path=str(image),
        endpoint_url="https://right.example.com",
        access_key_id="AK",
        secret_key="SK",
        bucket="b",
        public_base="https://x/{key}",
    )
    assert out.get("error") is not True
    assert stub_s3.factory_args["endpoint_url"] == "https://right.example.com"


def test_upload_with_secret_prefix(stub_s3, fake_secrets, tmp_path):
    """Per-agent prefix lets multiple agents have separate creds."""
    fake_secrets.update({
        "agent:abc:cdn_endpoint_url": "https://s3.example.com",
        "agent:abc:cdn_access_key_id": "AK",
        "agent:abc:cdn_secret_key": "SK",
        "agent:abc:cdn_bucket": "tenant-abc",
        "agent:abc:cdn_public_base": "https://cdn.abc/{key}",
    })
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    out = tool(local_path=str(image), secret_prefix="agent:abc:")
    assert out.get("error") is not True
    assert "https://cdn.abc/" in out["url"]


def test_upload_custom_key_template(stub_s3, fake_secrets, tmp_path):
    _seed_full_creds(fake_secrets)
    image = tmp_path / "hero.png"
    image.write_bytes(b"png")
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    out = tool(
        local_path=str(image),
        key_template="iba/{filename}",
    )
    assert out["key"] == "iba/hero.png"
    assert out["url"] == "https://cdn.iba.kz/iba/hero.png"


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_upload_missing_credentials(stub_s3, fake_secrets, tmp_path):
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    out = tool(local_path=str(image))
    assert out["error"] is True
    assert out["reason"] == "missing_credentials"
    assert "cdn_endpoint_url" in out["missing_secrets"]


def test_upload_path_outside_allow_list(stub_s3, fake_secrets, tmp_path):
    _seed_full_creds(fake_secrets)
    srv, _ = _build_server([str(tmp_path / "workspace")])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    out = tool(local_path="/etc/passwd")
    assert out["error"] is True
    assert out["reason"] == "path_access_denied"


def test_upload_not_found(stub_s3, fake_secrets, tmp_path):
    _seed_full_creds(fake_secrets)
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    out = tool(local_path=str(tmp_path / "missing.png"))
    assert out["error"] is True
    assert out["reason"] == "not_found"


def test_upload_directory_rejected(stub_s3, fake_secrets, tmp_path):
    _seed_full_creds(fake_secrets)
    sub = tmp_path / "sub"
    sub.mkdir()
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    out = tool(local_path=str(sub))
    assert out["error"] is True
    assert out["reason"] == "not_a_file"


def test_upload_s3_failure_classified(stub_s3, fake_secrets, tmp_path):
    _seed_full_creds(fake_secrets)
    stub_s3.put_error = RuntimeError("Access Denied")
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    out = tool(local_path=str(image))
    assert out["error"] is True
    assert out["reason"] == "upload_failed"
    assert "Access Denied" in out["detail"]


# ---------------------------------------------------------------------------
# audit + category gate
# ---------------------------------------------------------------------------


def test_upload_audit_records_path(stub_s3, fake_secrets, tmp_path):
    _seed_full_creds(fake_secrets)
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    srv, events = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    tool(local_path=str(image))
    success = [e for e in events if e.get("result") == "success"]
    assert success
    assert success[-1]["extra"]["local_path"] == str(image)


def test_cdn_category_disabled_refuses(stub_s3, fake_secrets, tmp_path):
    _seed_full_creds(fake_secrets)
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(
            enabled_categories=["database"],
            allowed_file_roots=[str(tmp_path)],
        ),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_cdn_tools(srv)
    tool = srv.fastmcp._tool_manager._tools["dialekt_cdn_upload"].fn
    with pytest.raises(ToolAccessDenied):
        tool(local_path=str(image))
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
