"""Public unauthenticated endpoints. Currently scoped to the agent
library catalog — first-time visitors can preview installable templates
before they license. Rate-limited at the edge (Cloudflare WAF rule)
rather than in-process; if abuse becomes real, add a slowapi gate here.

Distinct from authenticated /agents (tenant-private template store).
"""
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..routers.admin import get_pool

router = APIRouter(prefix="/public", tags=["public"])
logger = logging.getLogger(__name__)


def _row_to_entry(row) -> dict[str, Any]:
    """Shape a library_entries row for the catalog response.

    The manifest_yaml is the single source of truth — `name`,
    `description`, `language` are surfaced from there at request time
    (avoids denormalization drift). Tags and capability flags ARE
    columns (cached at seed time) so list filtering doesn't need to
    parse every YAML."""
    import yaml  # local import — health endpoint must not pull yaml
    try:
        m = yaml.safe_load(row["manifest_yaml"]) or {}
        meta = m.get("metadata", {}) if isinstance(m, dict) else {}
    except Exception:
        meta = {}
    tags = row["tags"]
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []
    return {
        "id": row["id"],
        "name": meta.get("name", row["id"]),
        "description": meta.get("description", ""),
        "language": meta.get("language", "ru"),
        "category": row["category"],
        "tags": tags or [],
        "requires_connection": bool(row["requires_connection"]),
        "requires_mcp": bool(row["requires_mcp"]),
        "version": row["version"],
        "signature": row["signature"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.get("/library")
async def list_library(
    request: Request,
    pool=Depends(get_pool),
    category: str | None = Query(None),
    requires_connection: bool | None = Query(None),
    search: str | None = Query(None, max_length=100),
):
    """Public catalog of installable agent templates.

    Returns published entries only. Filters:
    - `category` — exact match
    - `requires_connection` — bool
    - `search` — substring match against the entry id, manifest name,
      manifest description, and tags. Case-insensitive.

    Detailed manifest text is NOT included — clients fetch it via
    GET /public/library/{id} when the user clicks "Install" so the
    list response stays cheap.
    """
    where = ["published"]
    params: list[Any] = []
    if category:
        params.append(category)
        where.append(f"category = ${len(params)}")
    if requires_connection is not None:
        params.append(requires_connection)
        where.append(f"requires_connection = ${len(params)}")
    sql = f"""
        SELECT id, manifest_yaml, category, tags,
               requires_connection, requires_mcp, signature,
               version, updated_at
        FROM library_entries
        WHERE {' AND '.join(where)}
        ORDER BY category, id
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    entries = [_row_to_entry(r) for r in rows]
    if search:
        q = search.strip().lower()
        if q:
            entries = [
                e for e in entries
                if q in e["id"].lower()
                or q in e["name"].lower()
                or q in e["description"].lower()
                or any(q in str(t).lower() for t in e["tags"])
            ]
    return {"entries": entries}


@router.get("/library/{entry_id}")
async def get_library_entry(entry_id: str, pool=Depends(get_pool)):
    """Full entry including the manifest YAML — clients call this when
    the user clicks "Install" on a catalog card."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, manifest_yaml, category, tags,
                   requires_connection, requires_mcp, signature,
                   version, updated_at
            FROM library_entries
            WHERE id = $1 AND published
            """,
            entry_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Library entry not found")
    entry = _row_to_entry(row)
    entry["manifest_yaml"] = row["manifest_yaml"]
    return entry
