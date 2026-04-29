"""
Admin Ops router — AWAAZ-PROOF.
Provides admin dashboard, complaint management, AI summarisation,
contractor assignment, NGO request management, and scheduling.
"""
import json
import logging
import os
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from routers.auth import get_current_user
from services.summarization_service import summarize_complaint
from utils.admin_sanitize import sanitize_for_admin

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pool(request: Request):
    return request.app.state.pool


async def _admin_only(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def _id():
    return f"adm_{uuid.uuid4().hex[:16]}"


def _row(row):
    if not row:
        return None
    d = dict(row)
    # Convert date/datetime to string for JSON serialization
    for k, v in d.items():
        if isinstance(v, (datetime, date)):
            d[k] = v.isoformat()
    return sanitize_for_admin(d)


def _rows(rows):
    return sanitize_for_admin([_row(r) for r in rows])


# ── Pydantic models ───────────────────────────────────────────────────────────

class AssignBody(BaseModel):
    contractor_user_id: str
    due_date: str  # YYYY-MM-DD


class ResolveBody(BaseModel):
    resolved: bool
    admin_note: str = ""


class RejectBody(BaseModel):
    reason: str = ""


# ── 1. GET /dashboard ─────────────────────────────────────────────────────────

@router.get("/dashboard")
async def dashboard(request: Request, _: dict = Depends(_admin_only)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        total_complaints = await conn.fetchval("SELECT COUNT(*) FROM complaints") or 0
        high_confidence = await conn.fetchval(
            "SELECT COUNT(*) FROM complaints WHERE confidence_score >= 0.75"
        ) or 0
        critical_risk = await conn.fetchval(
            "SELECT COUNT(*) FROM ai_summaries WHERE risk_level = 'critical'"
        ) or 0
        pending_ngo = await conn.fetchval(
            "SELECT COUNT(*) FROM ngo_requests WHERE status = 'pending'"
        ) or 0
        resolved_this_week = await conn.fetchval("""
            SELECT COUNT(*) FROM complaints
            WHERE status = 'resolved'
            AND updated_at >= NOW() - INTERVAL '7 days'
        """) or 0
        total_breach = await conn.fetchval(
            "SELECT COALESCE(SUM(breach_value_inr), 0) FROM complaints"
        ) or 0

        # Top risk complaints
        top_risk_rows = await conn.fetch("""
            SELECT c.id, c.complaint_type, c.confidence_score, c.warranty_breach,
                   c.geohash, c.status, c.breach_value_inr,
                   s.risk_level, s.summary, s.risk_reason, s.recommended_action,
                   a.ward_id
            FROM complaints c
            LEFT JOIN ai_summaries s ON s.complaint_id = c.id
            LEFT JOIN assets a ON a.id = c.asset_id
            ORDER BY
                CASE s.risk_level
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                END,
                c.confidence_score DESC
            LIMIT 5
        """)

        # Pending assignments
        pending_assignments_rows = await conn.fetch("""
            SELECT c.id, c.complaint_type, c.confidence_score, c.status,
                   c.warranty_breach, c.geohash, a.ward_id
            FROM complaints c
            LEFT JOIN assets a ON a.id = c.asset_id
            LEFT JOIN complaint_assignments ca ON ca.complaint_id = c.id
            WHERE ca.id IS NULL AND c.status != 'resolved'
            ORDER BY c.confidence_score DESC
            LIMIT 10
        """)

        # Recent resolved
        recent_resolved_rows = await conn.fetch("""
            SELECT c.id, c.complaint_type, c.confidence_score, c.status,
                   c.updated_at, a.ward_id
            FROM complaints c
            LEFT JOIN assets a ON a.id = c.asset_id
            WHERE c.status = 'resolved'
            ORDER BY c.updated_at DESC
            LIMIT 5
        """)

    return {
        "total_complaints": total_complaints,
        "high_confidence": high_confidence,
        "critical_risk": critical_risk,
        "pending_ngo_requests": pending_ngo,
        "resolved_this_week": resolved_this_week,
        "total_breach_value_inr": total_breach,
        "top_risk_complaints": _rows(top_risk_rows),
        "pending_assignments": _rows(pending_assignments_rows),
        "recent_resolved": _rows(recent_resolved_rows),
    }


# ── 2. GET /complaints ────────────────────────────────────────────────────────

@router.get("/complaints-list")
async def complaints_list(
    request: Request,
    status: Optional[str] = Query(None),
    risk: Optional[str] = Query(None),
    assigned: Optional[str] = Query(None),
    _: dict = Depends(_admin_only),
):
    pool = _pool(request)
    query = """
        SELECT c.*, s.risk_level, s.summary, s.risk_reason, s.recommended_action,
               ca.contractor_name, ca.due_date AS assignment_due_date, ca.status AS assignment_status,
               a.ward_id
        FROM complaints c
        LEFT JOIN ai_summaries s ON s.complaint_id = c.id
        LEFT JOIN complaint_assignments ca ON ca.complaint_id = c.id
        LEFT JOIN assets a ON a.id = c.asset_id
        WHERE 1=1
    """
    params = []
    idx = 1

    if status:
        query += f" AND c.status = ${idx}"
        params.append(status)
        idx += 1

    if risk:
        query += f" AND s.risk_level = ${idx}"
        params.append(risk)
        idx += 1

    if assigned == "true":
        query += " AND ca.id IS NOT NULL"
    elif assigned == "false":
        query += " AND ca.id IS NULL"

    query += " ORDER BY c.created_at DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return {"complaints": _rows(rows), "count": len(rows)}


# ── 3. POST /complaints/{id}/summarise ─────────────────────────────────────────

@router.post("/complaints/{complaint_id}/summarise")
async def summarise_with_gemini(complaint_id: str, request: Request, _: dict = Depends(_admin_only)):
    try:
        pool = _pool(request)
        async with pool.acquire() as conn:
            complaint = _row(await conn.fetchrow("SELECT * FROM complaints WHERE id=$1", complaint_id))
            if not complaint:
                raise HTTPException(status_code=404, detail="Complaint not found")

        text = (
            f"Type: {complaint.get('complaint_type', 'unknown')}\n"
            f"Description: {complaint.get('description', 'No description')}\n"
            f"Confidence: {complaint.get('confidence_score', 0)}\n"
            f"Warranty breach: {complaint.get('warranty_breach', False)}\n"
            f"Breach value INR: {complaint.get('breach_value_inr', 0)}\n"
            f"Status: {complaint.get('status', 'unverified')}\n"
            "Risk guide: critical=warranty breach+injury signal+confidence>=0.75; "
            "high=warranty breach OR confidence>=0.75; medium=confidence>=0.55; low=everything else."
        )
        gemini = await summarize_complaint(text)
        risk_level = str(gemini.get("risk_level") or gemini.get("priority") or "medium").lower()
        if risk_level not in {"critical", "high", "medium", "low"}:
            risk_level = "medium"

        result = {
            "summary": gemini.get("summary") or complaint.get("description") or "No description",
            "risk_level": risk_level,
            "risk_reason": gemini.get("risk_reason") or "Manual review needed",
            "recommended_action": gemini.get("recommended_action") or "Inspect site",
            "priority": gemini.get("priority") or risk_level,
            "category": gemini.get("category") or complaint.get("complaint_type") or "civic",
            "model": gemini.get("model"),
            "provider": gemini.get("provider") or "Google Gemini",
        }

        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO ai_summaries (id, complaint_id, summary, risk_level, risk_reason, recommended_action)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (complaint_id) DO UPDATE
                SET summary=$3, risk_level=$4, risk_reason=$5, recommended_action=$6, generated_at=NOW()
            """, f"ais_{uuid.uuid4().hex[:12]}", complaint_id,
                result["summary"], result["risk_level"], result["risk_reason"], result["recommended_action"])

        try:
            await request.app.state.service._log_action(
                action="ai_summary_generated",
                entity_type="complaint",
                entity_id=complaint_id,
                actor_id="gemini",
                payload={"risk_level": result["risk_level"], "model": result.get("model"), "provider": result.get("provider")},
            )
        except Exception as exc:
            logger.warning("ai summary audit log failed: %s", exc)

        return sanitize_for_admin(result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin summarise failed: %s", exc, exc_info=True)
        return {
            "summary": "No description",
            "risk_level": "medium",
            "risk_reason": "Manual review needed",
            "recommended_action": "Inspect site",
            "priority": "medium",
            "category": "civic",
            "provider": "Google Gemini",
        }

@router.post("/complaints/{complaint_id}/summarise-legacy-near")
async def summarise(complaint_id: str, request: Request, _: dict = Depends(_admin_only)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        complaint = _row(await conn.fetchrow("SELECT * FROM complaints WHERE id=$1", complaint_id))
        if not complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")

    from utils.near_ai import call as near_call, get_attestation_info

    prompt = f"""Analyse this civic complaint and return ONLY valid JSON (no markdown, no code fences):
{{
  "summary": "2-sentence plain English summary for admin",
  "risk_level": "critical|high|medium|low",
  "risk_reason": "one line why this risk level",
  "recommended_action": "specific action admin should take"
}}

Risk guide:
- critical = warranty breach + injury signal + confidence >= 0.75
- high = warranty breach OR confidence >= 0.75
- medium = confidence >= 0.55
- low = everything else

Complaint data:
- Type: {complaint.get('complaint_type', 'unknown')}
- Description: {complaint.get('description', 'No description')}
- Confidence: {complaint.get('confidence_score', 0)}
- Warranty breach: {complaint.get('warranty_breach', False)}
- Breach value INR: {complaint.get('breach_value_inr', 0)}
- Status: {complaint.get('status', 'unverified')}
"""

    result = near_call(prompt)
    if not result:
        result = {
            "summary": complaint.get("description", "No description"),
            "risk_level": "medium",
            "risk_reason": "Manual review needed — AI unavailable",
            "recommended_action": "Inspect site manually"
        }
    
    tee_info = get_attestation_info()
    result["tee_attestation"] = tee_info

    # Upsert into ai_summaries
    summary_id = f"ais_{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO ai_summaries (id, complaint_id, summary, risk_level, risk_reason, recommended_action)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (complaint_id) DO UPDATE
            SET summary=$3, risk_level=$4, risk_reason=$5, recommended_action=$6, generated_at=NOW()
        """, summary_id, complaint_id,
            result.get("summary", ""),
            result.get("risk_level", "medium"),
            result.get("risk_reason", ""),
            result.get("recommended_action", ""))

    from services.service import Service
    from repos.repo import Repo
    svc = Service(Repo(pool))
    await svc._log_action(
        action="ai_summary_generated",
        entity_type="complaint",
        entity_id=complaint_id,
        actor_id="near_ai_tee",
        payload={
            "risk_level": result["risk_level"],
            "model": tee_info["model"],
            "tee_type": tee_info["tee_type"],
            "provider": tee_info["provider"],
        }
    )

    return result


# ── 4. POST /complaints/{id}/assign ────────────────────────────────────────────

@router.post("/complaints/{complaint_id}/assign")
async def assign(complaint_id: str, body: AssignBody, request: Request, user: dict = Depends(_admin_only)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        complaint = await conn.fetchrow("SELECT id FROM complaints WHERE id=$1", complaint_id)
        if not complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")

        # Look up contractor name
        profile = await conn.fetchrow(
            "SELECT org_name FROM org_profiles WHERE user_id=$1", body.contractor_user_id
        )
        contractor_name = profile["org_name"] if profile else body.contractor_user_id

        assignment_id = f"asgn_{uuid.uuid4().hex[:12]}"
        try:
            due = date.fromisoformat(body.due_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="due_date must be YYYY-MM-DD")

        await conn.execute("""
            INSERT INTO complaint_assignments (id, complaint_id, contractor_id, contractor_name, assigned_by, due_date)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, assignment_id, complaint_id, body.contractor_user_id, contractor_name,
            user.get("sub", "admin"), due)

        await conn.execute("UPDATE complaints SET status='assigned', updated_at=NOW() WHERE id=$1", complaint_id)

    return {
        "id": assignment_id,
        "complaint_id": complaint_id,
        "contractor_id": body.contractor_user_id,
        "contractor_name": contractor_name,
        "due_date": body.due_date,
        "status": "assigned",
    }


# ── 5. PATCH /complaints/{id}/resolve ──────────────────────────────────────────

@router.patch("/complaints/{complaint_id}/resolve")
async def resolve(complaint_id: str, body: ResolveBody, request: Request, _: dict = Depends(_admin_only)):
    pool = _pool(request)
    new_status = "resolved" if body.resolved else "disputed"
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE complaints SET status=$2, updated_at=NOW() WHERE id=$1 RETURNING *
        """, complaint_id, new_status)
        if not row:
            raise HTTPException(status_code=404, detail="Complaint not found")
    return _row(row)


# ── 6. GET /ngo-requests-list ──────────────────────────────────────────────────

@router.get("/ngo-requests-list")
async def ngo_requests_list(request: Request, _: dict = Depends(_admin_only)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT r.*, p.org_name, p.org_type, p.region,
                   c.complaint_type, c.status AS complaint_status,
                   c.confidence_score, c.description, c.lat, c.lng, c.geohash,
                   u.name AS user_name, u.email AS user_email
            FROM ngo_requests r
            LEFT JOIN org_profiles p ON p.user_id = r.ngo_user_id
            LEFT JOIN complaints c ON c.id = r.complaint_id
            LEFT JOIN users u ON u.id = r.ngo_user_id
            ORDER BY r.created_at DESC
        """)
    return {"requests": _rows(rows), "count": len(rows)}


# ── 7. PATCH /ngo-requests/{id}/approve ────────────────────────────────────────

@router.patch("/ngo-requests-list/{request_id}/approve")
async def approve_ngo(request_id: str, request: Request, _: dict = Depends(_admin_only)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE ngo_requests SET status='approved', resolved_at=NOW() WHERE id=$1 RETURNING *
        """, request_id)
        if not row:
            raise HTTPException(status_code=404, detail="NGO request not found")

        row_dict = _row(row)
        complaint_details = None
        complaint = await conn.fetchrow("""
            SELECT c.*, a.ward_id, a.city
            FROM complaints c
            LEFT JOIN assets a ON a.id = c.asset_id
            WHERE c.id=$1
        """, row_dict.get("complaint_id"))
        if complaint:
            complaint_details = _row(complaint)

        # Check org_type
        org_profile = await conn.fetchrow(
            "SELECT org_type FROM org_profiles WHERE user_id=$1",
            row_dict.get("ngo_user_id")
        )
        org_type = org_profile["org_type"] if org_profile else "ngo"

    resp = {"approved": True, "complaint_details": complaint_details}
    if org_type == "contractor" and complaint_details:
        resp["complaint_address"] = complaint_details.get("description") or ""
        resp["complaint_ward"] = complaint_details.get("ward_id") or ""
    return resp


# ── 8. PATCH /ngo-requests/{id}/reject ─────────────────────────────────────────

@router.patch("/ngo-requests-list/{request_id}/reject")
async def reject_ngo(request_id: str, body: RejectBody, request: Request, _: dict = Depends(_admin_only)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE ngo_requests SET status='rejected', admin_note=$2, resolved_at=NOW()
            WHERE id=$1 RETURNING id, status
        """, request_id, body.reason)
        if not row:
            raise HTTPException(status_code=404, detail="NGO request not found")
    return {"rejected": True}


# ── 9. GET /contractors-list ───────────────────────────────────────────────────

@router.get("/contractors-list")
async def contractors_list(request: Request, _: dict = Depends(_admin_only)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*,
                   COALESCE(ac.cnt, 0) AS assignment_count
            FROM org_profiles p
            LEFT JOIN (
                SELECT contractor_id, COUNT(*) AS cnt
                FROM complaint_assignments
                GROUP BY contractor_id
            ) ac ON ac.contractor_id = p.user_id
            WHERE p.org_type = 'contractor'
            ORDER BY p.org_name
        """)
    return {"contractors": _rows(rows), "count": len(rows)}


# ── 10. GET /schedule ──────────────────────────────────────────────────────────

@router.get("/schedule")
async def schedule(request: Request, _: dict = Depends(_admin_only)):
    pool = _pool(request)
    today = date.today()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ca.*, c.complaint_type, c.status AS complaint_status,
                   c.confidence_score, c.geohash, a.ward_id
            FROM complaint_assignments ca
            JOIN complaints c ON c.id = ca.complaint_id
            LEFT JOIN assets a ON a.id = c.asset_id
            ORDER BY ca.due_date ASC
        """)

    overdue = []
    due_today = []
    upcoming = []
    for r in rows:
        item = _row(r)
        dd = r.get("due_date")
        if dd is None:
            upcoming.append(item)
        elif dd < today:
            overdue.append(item)
        elif dd == today:
            due_today.append(item)
        else:
            upcoming.append(item)

    return {"overdue": overdue, "due_today": due_today, "upcoming": upcoming}
