import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auth_security import decode_token
from utils.admin_sanitize import sanitize_for_admin

router = APIRouter(prefix="/ngo", tags=["ngo"])
admin_router = APIRouter(prefix="/admin", tags=["admin-ngo"])


class RequestAccessBody(BaseModel):
    complaint_id: str
    reason: str
    ngo_token: Optional[str] = None


class ConnectRequestBody(BaseModel):
    complaint_id: str
    message: Optional[str] = None


class AdminActionBody(BaseModel):
    admin_note: Optional[str] = None


def _bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return None


def _current_user(request: Request, token_from_body: Optional[str] = None) -> dict:
    token = _bearer_token(request) or token_from_body
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


def _require_partner(user: dict) -> dict:
    if user.get("role") not in ("moderator", "faculty", "ngo"):
        raise HTTPException(status_code=403, detail="NGO or contractor access required")
    return user


def _require_contractor(user: dict) -> dict:
    if user.get("role") != "moderator":
        raise HTTPException(status_code=403, detail="Contractor access required")
    return user


def _require_admin(user: dict) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _row(row) -> Optional[dict]:
    return dict(row) if row else None


def _ward_from_complaint(complaint: dict) -> str:
    if complaint.get("ward_id"):
        return str(complaint["ward_id"])
    geohash = complaint.get("geohash") or ""
    return f"Ward {geohash[:4] or 'Unknown'}"


async def _org_profile(conn, user_id: str) -> Optional[dict]:
    return _row(await conn.fetchrow(
        """
        SELECT p.*, u.name, u.email, u.role
        FROM org_profiles p
        JOIN users u ON u.id = p.user_id
        WHERE p.user_id=$1
        """,
        user_id,
    ))


async def _complaint_details(conn, complaint_id: str) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        SELECT c.*, a.ward_id, a.city, ct.contract_number
        FROM complaints c
        LEFT JOIN assets a ON a.id = c.asset_id
        LEFT JOIN contracts ct ON ct.id = c.contract_id
        WHERE c.id=$1
        """,
        complaint_id,
    )
    if not row:
        return None
    data = dict(row)
    data["ward"] = _ward_from_complaint(data)
    data["reporter_contact"] = None
    data["address"] = data.get("description") or data["ward"]
    return data


async def _contractor_details(conn, user_id: str) -> dict:
    profile = await _org_profile(conn, user_id)
    if profile:
        return profile
    user = _row(await conn.fetchrow("SELECT id AS user_id, name, email, role FROM users WHERE id=$1", user_id))
    return user or {"user_id": user_id}


@router.post("/request-access")
async def request_access(body: RequestAccessBody, request: Request):
    user = _require_partner(_current_user(request, body.ngo_token))

    async with request.app.state.pool.acquire() as conn:
        complaint = _row(await conn.fetchrow(
            "SELECT id,status,confidence_score FROM complaints WHERE id=$1",
            body.complaint_id,
        ))
        if not complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")
        if complaint.get("status") != "high_confidence" and float(complaint.get("confidence_score") or 0) < 0.75:
            raise HTTPException(status_code=422, detail="Complaint is not high confidence yet")

        request_id = f"ngo_req_{uuid.uuid4().hex[:12]}"
        row = await conn.fetchrow(
            """
            INSERT INTO ngo_requests(id,ngo_user_id,complaint_id,reason,type,message,status)
            VALUES($1,$2,$3,$4,'access',$4,'pending')
            RETURNING id,status
            """,
            request_id,
            user["sub"],
            body.complaint_id,
            body.reason,
        )
    return {"request_id": row["id"], "status": row["status"]}


@router.post("/connect-request")
async def connect_request(body: ConnectRequestBody, request: Request):
    user = _require_contractor(_current_user(request))

    async with request.app.state.pool.acquire() as conn:
        complaint = await _complaint_details(conn, body.complaint_id)
        if not complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")

        profile = await _org_profile(conn, user["sub"])
        contractor_region = (profile or {}).get("region") or ""
        complaint_region = complaint.get("ward_id") or complaint.get("city") or complaint.get("ward") or ""
        region_match = bool(
            contractor_region
            and complaint_region
            and contractor_region.lower() in str(complaint_region).lower()
        )

        request_id = f"ngo_req_{uuid.uuid4().hex[:12]}"
        row = await conn.fetchrow(
            """
            INSERT INTO ngo_requests(id,ngo_user_id,complaint_id,reason,type,message,region_match,status)
            VALUES($1,$2,$3,$4,'contractor_connect',$4,$5,'pending')
            RETURNING id,status
            """,
            request_id,
            user["sub"],
            body.complaint_id,
            body.message or "Contractor connection request",
            region_match,
        )
    return {"request_id": row["id"], "status": row["status"], "region_match": region_match}


@router.get("/my-requests")
async def my_requests(request: Request):
    user = _require_partner(_current_user(request))
    async with request.app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.*, c.complaint_type, c.status AS complaint_status,
                   c.confidence_score, c.breach_value_inr, c.created_at AS complaint_created_at,
                   c.description, c.geohash, c.lat, c.lng, a.ward_id, a.city,
                   ct.contract_number
            FROM ngo_requests r
            JOIN complaints c ON c.id = r.complaint_id
            LEFT JOIN assets a ON a.id = c.asset_id
            LEFT JOIN contracts ct ON ct.id = c.contract_id
            WHERE r.ngo_user_id=$1
            ORDER BY r.created_at DESC
            """,
            user["sub"],
        )

    requests = []
    for row in rows:
        item = dict(row)
        item["ward"] = _ward_from_complaint(item)
        if item.get("status") == "approved":
            item["complaint_details"] = {
                "id": item.get("complaint_id"),
                "complaint_type": item.get("complaint_type"),
                "description": item.get("description"),
                "lat": item.get("lat"),
                "lng": item.get("lng"),
                "ward": item.get("ward"),
                "address": item.get("description") or item.get("ward"),
                "contract_number": item.get("contract_number"),
                "reporter_contact": None,
                "admin_contact": "admin@awaaz.in",
            }
        requests.append(item)
    return {"requests": requests, "count": len(requests)}


@router.get("/requests")
async def solve_requests(request: Request):
    try:
        user = _current_user(request)
        async with request.app.state.pool.acquire() as conn:
            profile = await _org_profile(conn, user["sub"])
            if user.get("role") not in ("ngo", "faculty") or (profile and profile.get("org_type") != "ngo"):
                raise HTTPException(status_code=403, detail="NGO access required")

            rows = await conn.fetch(
                """
                SELECT sr.request_id, sr.grievance_id, sr.ngo_id, sr.note, sr.status,
                       sr.created_at, c.complaint_type, c.description, c.lat, c.lng,
                       c.report_count, c.contractor
                FROM solve_requests sr
                JOIN complaints c ON c.id = sr.grievance_id
                WHERE sr.ngo_id=$1
                ORDER BY sr.created_at DESC
                """,
                user["sub"],
            )
        result = []
        for row in rows:
            item = dict(row)
            if item.get("status") != "APPROVED":
                item["contractor"] = None
            result.append(sanitize_for_admin(item))
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="NGO request lookup failed") from exc


@admin_router.get("/ngo-requests")
async def admin_ngo_requests(request: Request):
    _require_admin(_current_user(request))
    async with request.app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.*, u.email AS user_email, u.name AS user_name, u.role,
                   p.org_name, p.org_type, p.region,
                   c.complaint_type, c.status AS complaint_status,
                   c.confidence_score, c.breach_value_inr, c.lat, c.lng
            FROM ngo_requests r
            JOIN users u ON u.id = r.ngo_user_id
            LEFT JOIN org_profiles p ON p.user_id = u.id
            JOIN complaints c ON c.id = r.complaint_id
            ORDER BY r.created_at DESC
            """
        )
    return {"requests": [dict(r) for r in rows], "count": len(rows)}


@admin_router.patch("/ngo-requests/{request_id}/approve")
async def approve_ngo_request(request_id: str, request: Request, body: AdminActionBody = None):
    _require_admin(_current_user(request))
    note = body.admin_note if body else None
    async with request.app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE ngo_requests
            SET status='approved', admin_note=$2, resolved_at=NOW()
            WHERE id=$1
            RETURNING *
            """,
            request_id,
            note,
        )
        if not row:
            raise HTTPException(status_code=404, detail="NGO request not found")

        complaint = await _complaint_details(conn, row["complaint_id"])
        contractor = await _contractor_details(conn, row["ngo_user_id"])

    return {
        "request_id": row["id"],
        "status": row["status"],
        "complaint_details": complaint,
        "contractor_details": contractor,
    }


@admin_router.patch("/ngo-requests/{request_id}/reject")
async def reject_ngo_request(request_id: str, request: Request, body: AdminActionBody = None):
    _require_admin(_current_user(request))
    note = body.admin_note if body else None
    async with request.app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE ngo_requests
            SET status='rejected', admin_note=$2, resolved_at=NOW()
            WHERE id=$1
            RETURNING id,status
            """,
            request_id,
            note,
        )
    if not row:
        raise HTTPException(status_code=404, detail="NGO request not found")
    return {"request_id": row["id"], "status": row["status"]}
