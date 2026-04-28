"""CDN upload tool for the MCP server.

Single tool — ``dialekt_cdn_upload`` — uploads a local file (PNG,
JPG, MP4, etc.) to an S3-compatible bucket and returns a public
HTTPS URL. Closes the gap from IBA_TZ_GAP.md: Instagram Graph API
requires media to live behind a public URL, so without this every
``dialekt_instagram_publish_*`` call from the smm_manager agent
would fail with "media URL not reachable".

Configurable per agent via secrets:

- ``cdn_endpoint_url``  — S3 endpoint (e.g. https://s3.eu-west-1.amazonaws.com,
                          https://<account>.r2.cloudflarestorage.com,
                          https://s3.us-west-001.backblazeb2.com)
- ``cdn_access_key_id`` — access key
- ``cdn_secret_key``    — secret access key
- ``cdn_bucket``        — bucket name
- ``cdn_region``        — region (some endpoints require it; R2 ignores)
- ``cdn_public_base``   — public base URL pattern, e.g.
                          ``https://cdn.iba.kz/{key}`` or
                          ``https://pub-<id>.r2.dev/{key}``. The tool
                          substitutes ``{key}`` with the uploaded
                          object key.

The tool uses the agent's per-agent secrets (``agent:{id}:{name}``
keychain entries) by default — configurable via ``secret_prefix``.
For one-off testing, every credential can also be passed inline.

Path safety: only files inside the server's ``allowed_file_roots``
allow-list can be uploaded. This prevents an agent from exfil-
trating arbitrary local files via the URL surface (e.g. ``~/.ssh/``
keys) by uploading them to an attacker-controlled bucket.
"""
from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from dialekt import secrets as secrets_module
from dialekt.mcp.server.tools._wrap import call_tool_wrapped
from dialekt.mcp.server.tools.file import PathAccessDenied, _resolve_safe

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


log = logging.getLogger("dialekt.mcp.server.tools.cdn")


DEFAULT_KEY_TEMPLATE = "uploads/{date}/{uuid}-{filename}"
SECRET_NAMES = (
    "cdn_endpoint_url",
    "cdn_access_key_id",
    "cdn_secret_key",
    "cdn_bucket",
    "cdn_region",
    "cdn_public_base",
)


def _build_s3_client(
    endpoint_url: str,
    access_key_id: str,
    secret_key: str,
    region: Optional[str],
):
    """Single seam for tests — production builds a real boto3
    client; tests substitute a stub that captures put_object calls."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_key,
        region_name=region or "auto",
    )


def _resolve_cred(name: str, override: Optional[str], secret_prefix: str) -> Optional[str]:
    """Pick the explicit override if non-empty, otherwise fall back
    to ``{secret_prefix}{name}`` from the keychain."""
    if isinstance(override, str) and override:
        return override
    return secrets_module.get_secret(f"{secret_prefix}{name}")


def _build_key(template: str, filename: str) -> str:
    import datetime as dt

    today = dt.date.today().isoformat()
    token = uuid.uuid4().hex[:12]
    return (
        template
        .replace("{date}", today)
        .replace("{uuid}", token)
        .replace("{filename}", filename)
    )


def _do_upload(
    server: "MCPServer",
    *,
    local_path: str,
    secret_prefix: str,
    endpoint_url: Optional[str],
    access_key_id: Optional[str],
    secret_key: Optional[str],
    bucket: Optional[str],
    region: Optional[str],
    public_base: Optional[str],
    key_template: str,
    content_type: Optional[str],
) -> dict:
    # Step 1: resolve + validate local path against allow-list.
    try:
        safe_path = _resolve_safe(
            local_path, list(server.config.allowed_file_roots)
        )
    except PathAccessDenied as e:
        return {
            "error": True,
            "reason": "path_access_denied",
            "detail": str(e),
        }
    if not safe_path.exists():
        return {
            "error": True,
            "reason": "not_found",
            "path": str(safe_path),
        }
    if not safe_path.is_file():
        return {
            "error": True,
            "reason": "not_a_file",
            "path": str(safe_path),
        }

    # Step 2: resolve credentials. Inline > keychain > error.
    endpoint = _resolve_cred("cdn_endpoint_url", endpoint_url, secret_prefix)
    ak = _resolve_cred("cdn_access_key_id", access_key_id, secret_prefix)
    sk = _resolve_cred("cdn_secret_key", secret_key, secret_prefix)
    bk = _resolve_cred("cdn_bucket", bucket, secret_prefix)
    rg = _resolve_cred("cdn_region", region, secret_prefix)
    pb = _resolve_cred("cdn_public_base", public_base, secret_prefix)

    missing = [
        ("cdn_endpoint_url", endpoint),
        ("cdn_access_key_id", ak),
        ("cdn_secret_key", sk),
        ("cdn_bucket", bk),
        ("cdn_public_base", pb),
    ]
    missing_names = [name for name, value in missing if not value]
    if missing_names:
        return {
            "error": True,
            "reason": "missing_credentials",
            "detail": (
                "missing CDN credentials. Set them via "
                "POST /agents/{id}/secrets or pass inline."
            ),
            "missing_secrets": missing_names,
        }

    # Step 3: build object key + content-type.
    key = _build_key(key_template, safe_path.name)
    if content_type is None:
        guessed, _ = mimetypes.guess_type(safe_path.name)
        content_type = guessed or "application/octet-stream"

    # Step 4: upload.
    try:
        client = _build_s3_client(endpoint, ak, sk, rg)
    except Exception as e:
        return {
            "error": True,
            "reason": "client_init_failed",
            "detail": str(e),
        }

    try:
        with safe_path.open("rb") as f:
            client.put_object(
                Bucket=bk,
                Key=key,
                Body=f,
                ContentType=content_type,
            )
    except Exception as e:
        return {
            "error": True,
            "reason": "upload_failed",
            "detail": str(e),
            "error_kind": type(e).__name__,
        }

    public_url = pb.replace("{key}", key)
    size_bytes = safe_path.stat().st_size
    return {
        "url": public_url,
        "key": key,
        "bucket": bk,
        "content_type": content_type,
        "size_bytes": size_bytes,
    }


def register_cdn_tools(server: "MCPServer") -> list[str]:
    """Attach the CDN upload tool. Returns registered names."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "Upload a local file to an S3-compatible bucket and return "
            "a public HTTPS URL. Local path must be inside the agent's "
            "allow-list (typically the workspace). Required secrets: "
            "cdn_endpoint_url, cdn_access_key_id, cdn_secret_key, "
            "cdn_bucket, cdn_public_base; optional: cdn_region. "
            "All can be overridden inline. Returns "
            "``{url, key, bucket, content_type, size_bytes}`` or "
            "``{error: true, reason, ...}``."
        )
    )
    def dialekt_cdn_upload(
        local_path: str,
        secret_prefix: str = "",
        endpoint_url: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        public_base: Optional[str] = None,
        key_template: str = DEFAULT_KEY_TEMPLATE,
        content_type: Optional[str] = None,
    ) -> dict:
        return call_tool_wrapped(
            server,
            "dialekt_cdn_upload",
            lambda: _do_upload(
                server,
                local_path=local_path,
                secret_prefix=secret_prefix,
                endpoint_url=endpoint_url,
                access_key_id=access_key_id,
                secret_key=secret_key,
                bucket=bucket,
                region=region,
                public_base=public_base,
                key_template=key_template,
                content_type=content_type,
            ),
            extra_audit={"local_path": local_path},
        )

    registered.append("dialekt_cdn_upload")
    return registered
