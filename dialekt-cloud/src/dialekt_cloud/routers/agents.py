"""Agent registry: publish, fetch, assign, unassign."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import get_current_user, get_pool
from ..services.validator import validate_manifest

router = APIRouter(prefix="/agents", tags=["agents"])
logger = logging.getLogger(__name__)


class PublishRequest(BaseModel):
    manifest_yaml: str


class AssignRequest(BaseModel):
    agent_id: str
    assigned_to_user_id: str


@router.get("/assigned-to-me")
async def assigned_to_me(
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_pool),
):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT at.id, at.name, at.manifest_yaml, at.version, at.updated_at,
                   aa.id AS assignment_id, aa.last_pulled_at
            FROM agent_assignments aa
            JOIN agent_templates at ON at.id = aa.agent_template_id
            WHERE aa.assigned_to = $1 AND at.tenant_id = $2
            ORDER BY at.updated_at DESC
            """,
            current_user["user_id"], current_user["tenant_id"],
        )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "manifest_yaml": r["manifest_yaml"],
            "version": r["version"],
            "updated_at": r["updated_at"].isoformat(),
            "assignment_id": str(r["assignment_id"]),
            "last_pulled_at": r["last_pulled_at"].isoformat() if r["last_pulled_at"] else None,
        }
        for r in rows
    ]


@router.get("/{agent_id}/manifest")
async def get_manifest(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_pool),
):
    async with pool.acquire() as conn:
        # Check access: agent must be assigned to this user OR user is admin/developer
        if current_user["role"] in ("admin", "developer"):
            row = await conn.fetchrow(
                "SELECT id, name, manifest_yaml, version FROM agent_templates WHERE id = $1 AND tenant_id = $2",
                agent_id, current_user["tenant_id"],
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT at.id, at.name, at.manifest_yaml, at.version
                FROM agent_templates at
                JOIN agent_assignments aa ON aa.agent_template_id = at.id
                WHERE at.id = $1 AND aa.assigned_to = $2
                """,
                agent_id, current_user["user_id"],
            )
        if not row:
            raise HTTPException(status_code=404)

        # Update last_pulled_at
        await conn.execute(
            """
            UPDATE agent_assignments SET last_pulled_at = now()
            WHERE agent_template_id = $1 AND assigned_to = $2
            """,
            agent_id, current_user["user_id"],
        )

    return {"id": str(row["id"]), "name": row["name"], "manifest_yaml": row["manifest_yaml"], "version": row["version"]}


@router.post("/publish")
async def publish_agent(
    body: PublishRequest,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_pool),
):
    if current_user["role"] not in ("admin", "developer"):
        raise HTTPException(status_code=403, detail="Only developers/admins can publish")

    result = validate_manifest(body.manifest_yaml)
    if not result["valid"]:
        raise HTTPException(status_code=422, detail={"error": "manifest_invalid", "errors": result["errors"], "warnings": result["warnings"]})

    # Extract name and version from YAML
    import yaml as _yaml
    try:
        manifest = _yaml.safe_load(body.manifest_yaml)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {e}")

    name = manifest.get("name", "Untitled Agent")
    version = str(manifest.get("version", "1.0.0"))

    async with pool.acquire() as conn:
        agent_id = await conn.fetchval(
            """
            INSERT INTO agent_templates(tenant_id, name, manifest_yaml, created_by, version)
            VALUES($1,$2,$3,$4,$5) RETURNING id
            """,
            current_user["tenant_id"], name, body.manifest_yaml,
            current_user["user_id"], version,
        )

    return {"agent_id": str(agent_id), "name": name, "version": version, "validation_result": result}


@router.post("/assign")
async def assign_agent(
    body: AssignRequest,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_pool),
):
    if current_user["role"] not in ("admin", "developer"):
        raise HTTPException(status_code=403)

    async with pool.acquire() as conn:
        # Verify agent belongs to this tenant
        exists = await conn.fetchval(
            "SELECT id FROM agent_templates WHERE id = $1 AND tenant_id = $2",
            body.agent_id, current_user["tenant_id"],
        )
        if not exists:
            raise HTTPException(status_code=404)

        assignment_id = await conn.fetchval(
            """
            INSERT INTO agent_assignments(tenant_id, agent_template_id, assigned_to, assigned_by)
            VALUES($1,$2,$3,$4)
            ON CONFLICT(agent_template_id, assigned_to) DO UPDATE SET assigned_by=EXCLUDED.assigned_by
            RETURNING id
            """,
            current_user["tenant_id"], body.agent_id,
            body.assigned_to_user_id, current_user["user_id"],
        )

    return {"assignment_id": str(assignment_id)}


@router.delete("/assign/{assignment_id}")
async def unassign_agent(
    assignment_id: str,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_pool),
):
    if current_user["role"] not in ("admin", "developer"):
        raise HTTPException(status_code=403)

    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM agent_assignments WHERE id = $1 AND tenant_id = $2 RETURNING id",
            assignment_id, current_user["tenant_id"],
        )
    if not deleted:
        raise HTTPException(status_code=404)
    return {"deleted": str(deleted)}
