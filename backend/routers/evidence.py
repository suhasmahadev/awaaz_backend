"""Evidence ingestion and before/after comparison router."""
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

EVIDENCE_DIR = Path(__file__).parent.parent / "static" / "evidence"

try:
    from utils.image_compare import compare_before_after
    CLIP_AVAILABLE = True
except RuntimeError:
    CLIP_AVAILABLE = False
    logger.warning("CLIP not available ??? /evidence/compare will return 503")


def _repo(request: Request):
    return request.app.state.repo

def _svc(request: Request):
    return request.app.state.service


def _stored_static_path(filename: str) -> str:
    return f"static/evidence/{filename}"


def _evidence_disk_path(stored_path: str) -> Path:
    value = stored_path or ""
    if value.startswith("/static/evidence/"):
        return Path(__file__).parent.parent / value.lstrip("/")
    if value.startswith("static/evidence/"):
        return Path(__file__).parent.parent / value
    return Path(value)


def _safe_upload_name(upload: UploadFile, prefix: str) -> str:
    original = Path(upload.filename or "upload").name
    ext = Path(original).suffix or ".jpg"
    return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}{ext}"


async def _save_photo(upload: UploadFile, prefix: str) -> tuple[str, str]:
    from utils.hashing import hash_evidence_payload

    file_bytes = await upload.read()
    state_hash = hash_evidence_payload(file_bytes)
    filename = _safe_upload_name(upload, prefix)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    dest = EVIDENCE_DIR / filename

    try:
        import aiofiles

        async with aiofiles.open(dest, "wb") as f:
            await f.write(file_bytes)
    except ImportError:
        dest.write_bytes(file_bytes)

    return _stored_static_path(filename), state_hash


@router.post("/submit", status_code=status.HTTP_201_CREATED)
async def submit_evidence(
    request: Request,
    complaint_id: str = Form(...),
    anon_id: str = Form(...),
    evidence_type: str = Form(...),    # photo | video | sensor | text
    state_type: str = Form(...),       # before | after
    lat: float = Form(...),
    lng: float = Form(...),
    tee_sign: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    sensor_json: Optional[str] = Form(None),
):
    """
    Submit evidence for a complaint.
    - Files are saved to /static/evidence/ and SHA-256 hashed.
    - If tee_sign=True, HMAC-SHA256 attestation is added.
    - If state_type='after', confidence recalculation is triggered.
    """
    if evidence_type not in ("photo", "video", "sensor", "text", "secondary_report"):
        raise HTTPException(status_code=422, detail="Invalid evidence_type")
    if state_type not in ("before", "after"):
        raise HTTPException(status_code=422, detail="state_type must be 'before' or 'after'")

    # Verify complaint exists
    complaint = await _repo(request).get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    file_path: Optional[str] = None
    state_hash: Optional[str] = None
    payload_bytes: Optional[bytes] = None

    if file:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        ext = Path(file.filename or "file").suffix
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = EVIDENCE_DIR / filename
        payload_bytes = await file.read()
        dest.write_bytes(payload_bytes)
        file_path = _stored_static_path(filename)
        from utils.hashing import hash_evidence_payload
        state_hash = hash_evidence_payload(payload_bytes)

    # TEE signing
    tee_signed = False
    attestation = None
    if tee_sign and payload_bytes:
        from utils.tee import sign_evidence_payload
        sign_payload = {
            "complaint_id": complaint_id,
            "anon_id": anon_id,
            "state_hash": state_hash,
            "lat": lat,
            "lng": lng,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        attestation = sign_evidence_payload(sign_payload)
        tee_signed = True

    # Parse sensor data
    sensor_data = None
    if sensor_json:
        import json
        try:
            sensor_data = json.loads(sensor_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="sensor_json is not valid JSON")

    from models.data_models import Evidence
    evidence = await _repo(request).insert_evidence(Evidence(
        complaint_id=complaint_id,
        anon_id=anon_id,
        evidence_type=evidence_type,
        file_path=file_path,
        state_hash=state_hash,
        state_type=state_type,
        lat=lat,
        lng=lng,
        timestamp=datetime.now(timezone.utc).isoformat(),
        tee_signed=tee_signed,
        sensor_data=sensor_data,
    ))

    # Auto-recalculate if after state submitted
    new_confidence = None
    if state_type == "after":
        breakdown = await _svc(request).recalculate_confidence(complaint_id)
        new_confidence = breakdown.confidence

    result = {
        "evidence_id": evidence.id,
        "state_hash": state_hash,
        "file_path": file_path,
        "tee_signed": tee_signed,
    }
    if new_confidence is not None:
        result["new_confidence"] = new_confidence
        result["confidence_bump_note"] = "after_state_submitted signal applied"
    if attestation:
        result["attestation"] = attestation

    return result


@router.get("/complaint/{complaint_id}")
async def get_complaint_evidence(complaint_id: str, request: Request):
    """Returns all evidence images for a complaint."""
    rows = await _repo(request).get_evidence_by_complaint(complaint_id)
    return {"evidence": [dict(r) for r in rows]}


@router.post("/support")
async def upload_support(
    request: Request,
    complaint_id: str = Form(...),
    anon_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a support photo that corroborates a complaint visually."""
    complaint = await _repo(request).get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    file_path, state_hash = await _save_photo(file, "ev_support")
    ev_id = f"ev_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    svc = _svc(request)
    await svc.get_or_create_anon(anon_id)
    await svc.repo.insert_evidence_raw(
        ev_id, complaint_id, anon_id, "photo",
        file_path, state_hash, "support",
        0.0, 0.0, "now", False,
    )
    breakdown = await svc.recalculate_confidence(complaint_id)

    return {
        "evidence_id": ev_id,
        "file_path": file_path,
        "state_hash": state_hash,
        "new_confidence": breakdown.confidence,
        "tier": breakdown.threshold_tier,
    }


@router.post("/verify")
async def upload_verification(
    request: Request,
    complaint_id: str = Form(...),
    anon_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload an after-state verification photo for a complaint."""
    complaint = await _repo(request).get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    file_path, state_hash = await _save_photo(file, "ev_after")
    ev_id = f"ev_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    svc = _svc(request)
    await svc.get_or_create_anon(anon_id)
    await svc.repo.insert_evidence_raw(
        ev_id, complaint_id, anon_id, "photo",
        file_path, state_hash, "after",
        0.0, 0.0, "now", False,
    )
    breakdown = await svc.recalculate_confidence(complaint_id)

    return {
        "evidence_id": ev_id,
        "file_path": file_path,
        "state_hash": state_hash,
        "new_confidence": breakdown.confidence,
        "tier": breakdown.threshold_tier,
        "message": "Verification photo uploaded. Run /verify/before-after to compare.",
    }


@router.post("/compare/{complaint_id}")
async def compare_evidence(complaint_id: str, request: Request):
    """
    Runs CLIP before/after image comparison.
    Requires both before and after evidence records in DB.
    Returns 503 if CLIP is not installed.
    """
    if not CLIP_AVAILABLE:
        return JSONResponse(
            status_code=503,
            content={
                "error": "image_comparison_unavailable",
                "message": "CLIP model not loaded. Install: pip install git+https://github.com/openai/CLIP.git",
                "is_mock": True,
            },
        )

    complaint = await _repo(request).get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    evidence_list = await _repo(request).get_evidence_by_complaint(complaint_id)
    photos = [e for e in evidence_list if e.get("evidence_type") == "photo"]

    before = next((e for e in photos if e.get("state_type") == "before"), None)
    after  = next((e for e in photos if e.get("state_type") == "after"), None)

    if not before:
        raise HTTPException(status_code=422, detail="No 'before' photo evidence found for this complaint")
    if not after:
        raise HTTPException(status_code=422, detail="No 'after' photo evidence found for this complaint. Submit after-state evidence first.")

    before_path = str(_evidence_disk_path(before["file_path"]))
    after_path = str(_evidence_disk_path(after["file_path"]))

    try:
        result = compare_before_after(before_path, after_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("CLIP comparison failed for %s: %s", complaint_id, exc)
        raise HTTPException(status_code=500, detail=f"Comparison failed: {exc}")

    # Update complaint status based on result
    if result.change_detected:
        await _repo(request).update_complaint_status(complaint_id, "resolved")
    else:
        await _repo(request).update_complaint_status(complaint_id, "disputed")

    # Recalculate confidence with new status
    breakdown = await _svc(request).recalculate_confidence(complaint_id)

    return {
        **result.to_dict(),
        "complaint_status": "resolved" if result.change_detected else "disputed",
        "new_confidence": breakdown.confidence,
    }


@router.get("/{evidence_id}")
async def get_evidence(evidence_id: str, request: Request):
    """Get evidence record and its state hash."""
    ev = await _repo(request).get_evidence_by_id(evidence_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return ev
