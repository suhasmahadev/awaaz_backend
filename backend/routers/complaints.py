"""
Complaints router — AWAAZ-PROOF.
ANTIGRAVITY: complete rewrite. Original called service methods that didn't exist
(submit_complaint, get_area_complaints, cast_vote, etc.).
All endpoints now use app.state.repo/service via Request injection.
All validation now raises proper HTTP errors instead of returning error dicts.
"""
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from services.localization import (
    display_status,
    format_response,
    generate_voice,
    normalize_language,
    translate_text,
)

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_COMPLAINT_TYPES = frozenset({
    "pothole", "no_water", "garbage", "drain", "street_light", "other"
})


class NewComplaintBody(BaseModel):
    anon_id: str
    complaint_type: str
    lat: float
    lng: float
    description: Optional[str] = None
    language: Optional[str] = "en"


class VoteBody(BaseModel):
    anon_id: str
    vote_type: str  # corroborate | dispute


def _repo(request: Request):
    return request.app.state.repo


def _svc(request: Request):
    return request.app.state.service


def _request_language(request: Request, body_language: Optional[str] = None) -> str:
    return normalize_language(
        body_language
        or request.headers.get("X-User-Language")
        or request.headers.get("Accept-Language")
    )


async def _save_comment_image(file: UploadFile) -> tuple[str, str]:
    from utils.hashing import hash_evidence_payload

    file_bytes = await file.read()
    image_hash = hash_evidence_payload(file_bytes)
    safe_name = Path(file.filename or "comment.jpg").name
    ext = Path(safe_name).suffix or ".jpg"
    filename = f"img_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}{ext}"
    evidence_dir = Path(__file__).parent.parent / "static" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    dest = evidence_dir / filename
    try:
        import aiofiles

        async with aiofiles.open(dest, "wb") as f:
            await f.write(file_bytes)
    except ImportError:
        dest.write_bytes(file_bytes)

    return f"static/evidence/{filename}", image_hash


async def _complaint_created_payload(result: dict, user_language: str) -> dict:
    agent_json = {"status": "success", "action": "complaint_created", "data": result}
    text_response = format_response(agent_json, user_language)
    voice = await generate_voice(text_response, user_language)
    complaint_id = result.get("complaint_id") or result.get("id")

    return {
        "grievance_id": complaint_id,
        "complaint_id": complaint_id,
        "text_response": voice["text"],
        "audio_url": voice["audio_url"],
        **{k: v for k, v in result.items() if k not in {"complaint_id", "id"}},
    }


# ── POST /complaints/new ───────────────────────────────────────────────────────
@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/new", status_code=status.HTTP_201_CREATED)
async def new_complaint(body: NewComplaintBody, request: Request):
    """
    Create a new anonymous complaint.

    ANTIGRAVITY: validates anon_id exists before inserting (was missing).
    Initial confidence = 0.30 (single_report only).
    """
    if body.complaint_type not in VALID_COMPLAINT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid complaint_type. Must be one of: {sorted(VALID_COMPLAINT_TYPES)}",
        )

    # ANTIGRAVITY: verify anon_id exists — raw fingerprints must not be used as anon_id
    reporter = await _repo(request).get_anon_reporter(body.anon_id)
    if not reporter:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "anon_id_not_found",
                "message": "Call POST /auth/anon first to obtain a valid anon_id.",
            },
        )

    try:
        user_language = _request_language(request, body.language)
        description_en = await translate_text(
            body.description,
            target_language="en",
            source_language=user_language,
        )
        result = await _svc(request).create_complaint(
            anon_id=body.anon_id,
            complaint_type=body.complaint_type,
            lat=body.lat,
            lng=body.lng,
            description=description_en,
        )
        return await _complaint_created_payload(result, user_language)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("new_complaint failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Complaint creation failed")


# ── GET /complaints/area ───────────────────────────────────────────────────────
@router.get("/area")
async def area(
    lat: float = Query(...),
    lng: float = Query(...),
    radius_km: float = Query(1.0),
    request: Request = None,
):
    """
    Get complaints near lat/lng sorted by confidence DESC.
    Uses geohash prefix matching (precision 5 ≈ 5km, precision 6 ≈ 1.2km).
    """
    from utils.geo import coords_to_geohash
    geohash_prefix = coords_to_geohash(lat, lng, 5)
    complaints = await _repo(request).list_complaints_by_area(geohash_prefix)
    return {"status": "success", "complaints": complaints, "count": len(complaints)}


# ── GET /complaints/mine ───────────────────────────────────────────────────────
@router.get("/history")
async def history(
    request: Request,
    fingerprint: Optional[str] = Query(None),
    anon_id: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    x_fingerprint: str = Header(None, alias="X-Fingerprint"),
    x_anon_id: str = Header(None, alias="X-Anon-Id"),
    x_user_language: str = Header(None, alias="X-User-Language"),
):
    """
    Fetch complaint history by fingerprint.

    The fix is the JOIN through anon_users: complaints store anon_id, while
    the browser can recreate the raw fingerprint.
    """
    user_language = normalize_language(language or x_user_language)
    lookup_fingerprint = (fingerprint or x_fingerprint or "").strip()
    lookup_anon_id = (anon_id or x_anon_id or "").strip()

    if lookup_anon_id:
        raw_rows = await _repo(request).list_complaints_by_anon(lookup_anon_id)
        rows = [
            {
                "grievance_id": row.get("id"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
            }
            for row in raw_rows
        ]
    elif lookup_fingerprint:
        rows = await _repo(request).list_complaint_history_by_fingerprint(lookup_fingerprint)
    else:
        raise HTTPException(
            status_code=422,
            detail="anon_id query parameter, X-Anon-Id header, X-Fingerprint header, or fingerprint query parameter required",
        )

    history_items = []
    for row in rows:
        item = {
            "grievance_id": row.get("grievance_id"),
            "status": display_status(row.get("status")),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }
        text_response = format_response(
            {"status": "success", "action": "complaint_history_item", "data": item},
            user_language,
        )
        voice = await generate_voice(text_response, user_language)
        item["text_response"] = voice["text"]
        item["audio_url"] = voice["audio_url"]
        history_items.append(item)

    return history_items


@router.get("/mine")
@router.get("/my-complaints")
async def mine(
    request: Request,
    anon_id: Optional[str] = Query(None),
    x_anon_id: str = Header(None, alias="X-Anon-Id"),
):
    """Get all complaints submitted by this anon reporter."""
    lookup_anon_id = (anon_id or x_anon_id or "").strip()
    if not lookup_anon_id:
        raise HTTPException(status_code=422, detail="anon_id query parameter or X-Anon-Id header required")
    complaints = await _repo(request).list_complaints_by_anon(lookup_anon_id)
    return {"status": "success", "complaints": complaints, "count": len(complaints)}


# ── GET /complaints/{id} ───────────────────────────────────────────────────────
@router.post("/{complaint_id}/comment")
async def add_comment(
    complaint_id: str,
    request: Request,
    anon_id: str = Form(...),
    comment_type: str = Form("neutral"),
    text: str = Form(...),
    file: UploadFile = File(None),
):
    """Add a support, verification, or neutral comment to a complaint."""
    if comment_type not in ("support", "verification", "neutral"):
        raise HTTPException(status_code=422, detail="Invalid comment_type")
    if len((text or "").strip()) < 3:
        raise HTTPException(status_code=422, detail="Comment too short")

    complaint = await _repo(request).get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    await _svc(request).get_or_create_anon(anon_id)
    image_path = None
    image_hash = None
    if file and file.filename:
        image_path, image_hash = await _save_comment_image(file)

    comment = await _repo(request).insert_comment(
        complaint_id=complaint_id,
        anon_id=anon_id,
        comment_type=comment_type,
        text=text.strip(),
        image_path=image_path,
        image_hash=image_hash,
    )
    return {"success": True, "data": comment}


@router.get("/{complaint_id}/comments")
async def get_comments(complaint_id: str, request: Request):
    complaint = await _repo(request).get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    rows = await _repo(request).list_comments(complaint_id)
    return {"comments": rows}


@router.get("/{complaint_id}/detail")
async def get_complaint_detail(complaint_id: str, request: Request):
    data = await _repo(request).get_complaint_with_evidence(complaint_id)
    if not data:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return data


@router.get("/{complaint_id}")
async def get_complaint(complaint_id: str, request: Request):
    """Get complaint detail + evidence list."""
    complaint = await _repo(request).get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    evidence = await _repo(request).get_evidence_by_complaint(complaint_id)
    return {"status": "success", "complaint": complaint, "evidence": evidence}


# ── POST /complaints/{id}/vote ─────────────────────────────────────────────────
@router.post("/{complaint_id}/vote")
async def vote(complaint_id: str, body: VoteBody, request: Request):
    """
    Submit a corroborate/dispute vote.

    ANTIGRAVITY: all three checks now raise proper HTTP errors:
    - 422 for invalid vote_type
    - 404 if complaint not found
    - 403 for self-vote (reporter voting on own complaint)
    - 409 for duplicate vote
    - 429 (flagged) if > 20 votes in last hour — reporter flagged, vote still processed
    Confidence is recalculated after each valid vote.
    """
    if body.vote_type not in ("corroborate", "dispute"):
        raise HTTPException(
            status_code=422,
            detail="vote_type must be 'corroborate' or 'dispute'",
        )

    complaint = await _repo(request).get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # ANTIGRAVITY: self-vote check using repo.is_own_complaint()
    is_own = await _repo(request).is_own_complaint(complaint_id, body.anon_id)
    if is_own:
        raise HTTPException(
            status_code=403,
            detail={"error": "self_vote_not_allowed", "message": "Cannot vote on your own complaint"},
        )

    # ANTIGRAVITY: duplicate vote check using EXISTS query
    already_voted = await _repo(request).has_voted(complaint_id, body.anon_id)
    if already_voted:
        raise HTTPException(
            status_code=409,
            detail={"error": "already_voted", "message": "You have already voted on this complaint"},
        )

    # ANTIGRAVITY: anti-gaming — flag reporter if > 20 votes last hour
    # Vote is still processed but reporter trust_tier is set to 'flagged'
    recent_votes = await _repo(request).count_votes_by_anon_last_hour(body.anon_id)
    flagged = False
    if recent_votes > 20:
        await _repo(request).flag_anon_reporter(body.anon_id)
        flagged = True
        logger.warning(
            "vote [%s]: anon_id %s...%s flagged for %d votes in last hour",
            complaint_id, body.anon_id[:8], body.anon_id[-4:], recent_votes,
        )

    from models.data_models import Vote
    vote_record = await _repo(request).insert_vote(
        Vote(
            complaint_id=complaint_id,
            anon_id=body.anon_id,
            vote_type=body.vote_type,
        )
    )

    # Recalculate confidence after vote — excludes flagged reporters from signals
    breakdown = await _svc(request).recalculate_confidence(complaint_id)

    result = {
        "status": "success",
        "vote_id": vote_record.id,
        "new_confidence": breakdown.confidence,
        "threshold_tier": breakdown.threshold_tier,
        "auto_escalate": breakdown.auto_escalate,
        "message": breakdown.message,
    }
    if flagged:
        result["warning"] = "Vote rate limit exceeded. Account flagged for review."
    return result


# ── PATCH /complaints/{id}/recalculate ────────────────────────────────────────
@router.patch("/{complaint_id}/recalculate")
async def recalculate(complaint_id: str, request: Request):
    """Trigger confidence recalculation manually. Idempotent."""
    complaint = await _repo(request).get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    breakdown = await _svc(request).recalculate_confidence(complaint_id)
    return {"status": "success", **breakdown.to_dict()}
