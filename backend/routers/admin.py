"""
Admin router — AWAAZ-PROOF.
ANTIGRAVITY: rewrote from bare repo=Repo() (no pool) to Request-injected pattern.
All endpoints use request.app.state.repo / request.app.state.service.
Requires admin/moderator JWT for all endpoints except /seed (kept open for demo).
"""
import json
import logging
import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from routers.auth import get_current_user
from utils.hashing import verify_audit_signature

logger = logging.getLogger(__name__)
router = APIRouter()

DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "seed_contracts.json"
)
_ENCLAVE_KEY: str = os.environ.get("ENCLAVE_KEY", "")


def _repo(request: Request):
    return request.app.state.repo


def _svc(request: Request):
    return request.app.state.service


async def _admin_only(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Admin or moderator access required")
    return current_user


def _add_months(d: date, months: int) -> date:
    year  = d.year + (d.month + months - 1) // 12
    month = (d.month + months - 1) % 12 + 1
    return date(year, month, min(d.day, 28))


# ── GET /admin/overview ────────────────────────────────────────────────────────
@router.get("/overview")
async def overview(
    request: Request,
    _: dict = Depends(_admin_only),
):
    """System-wide statistics. Admin/moderator only."""
    try:
        return await _repo(request).get_overview_stats()
    except Exception as exc:
        logger.error("overview failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /admin/complaints ──────────────────────────────────────────────────────
@router.get("/complaints")
async def complaints(
    request: Request,
    status: str = Query(None),
    city: str = Query(None),
    _: dict = Depends(_admin_only),
):
    """All complaints with optional status/city filters. Admin/moderator only."""
    try:
        items = await _repo(request).list_all_complaints(status=status, city=city)
        return {"complaints": items, "count": len(items)}
    except Exception as exc:
        logger.error("admin/complaints failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /admin/contractors ─────────────────────────────────────────────────────
@router.get("/contractors")
async def contractors(
    request: Request,
    _: dict = Depends(_admin_only),
):
    """All contractors with live failure scores. Admin/moderator only."""
    try:
        data = await _svc(request).get_ledger()
        return {"contractors": data, "count": len(data)}
    except Exception as exc:
        logger.error("admin/contractors failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /admin/audit-log ───────────────────────────────────────────────────────
@router.get("/audit-log")
async def audit_log(
    request: Request,
    limit: int = Query(100),
    _: dict = Depends(_admin_only),
):
    """Signed audit log with signature validity flags. Admin/moderator only."""
    try:
        entries = await _repo(request).list_audit_log(limit=limit)
        for entry in entries:
            payload   = entry.get("payload") or {}
            signature = entry.get("signature") or ""
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            entry["signature_valid"] = (
                verify_audit_signature(payload, signature, _ENCLAVE_KEY)
                if _ENCLAVE_KEY else False
            )
        return {"audit_log": entries, "count": len(entries)}
    except Exception as exc:
        logger.error("admin/audit-log failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /admin/seed ───────────────────────────────────────────────────────────
@router.post("/seed")
async def seed(request: Request, _: dict = Depends(_admin_only)):
    """
    Load synthetic seed data from data/seed_contracts.json.
    Returns: {"assets": N, "contractors": N, "contracts": N, "clusters": N}
    """
    if not os.path.exists(DATA_FILE):
        raise HTTPException(
            status_code=404,
            detail="seed_contracts.json not found in /data/. Create it first.",
        )

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"seed_contracts.json is not valid JSON: {exc}")

    from models.data_models import Asset, Contract, Contractor
    from utils.geo import coords_to_geohash

    loaded = {"assets": 0, "contractors": 0, "contracts": 0, "clusters": 0}
    contractors_by_reg: dict[str, object] = {}

    for entry in entries:
        c_data  = entry["contractor"]
        a_data  = entry["asset"]
        co_data = entry["contract"]

        reg_no = c_data.get("registration_no", "")
        if reg_no not in contractors_by_reg:
            existing = await _repo(request).list_contractors()
            existing_c = next(
                (e for e in existing if e.get("registration_no") == reg_no), None
            )
            if existing_c:
                # Create a stub object with .id for downstream use
                class _Stub:
                    id = existing_c["id"]
                contractors_by_reg[reg_no] = _Stub()
            else:
                contractor = await _repo(request).insert_contractor(Contractor(
                    name=c_data["name"],
                    registration_no=reg_no,
                    city=a_data.get("city", "Bengaluru"),
                    active_contracts=1,
                ))
                contractors_by_reg[reg_no] = contractor
                loaded["contractors"] += 1

        contractor_obj = contractors_by_reg[reg_no]

        lat = float(a_data["lat"])
        lng = float(a_data["lng"])
        gh  = coords_to_geohash(lat, lng, 7)

        asset = await _repo(request).insert_asset(Asset(
            asset_type=a_data["type"],
            geohash=gh,
            lat=lat,
            lng=lng,
            ward_id=a_data.get("ward_id"),
            city=a_data.get("city", "Bengaluru"),
        ))
        loaded["assets"] += 1

        completion = date.fromisoformat(co_data["completion_date"])
        warranty_months = int(co_data.get("warranty_months", 24))
        expiry = _add_months(completion, warranty_months)

        await _repo(request).insert_contract(Contract(
            asset_id=asset.id,
            contractor_id=contractor_obj.id,
            contract_number=co_data["contract_number"],
            contract_value_inr=co_data["contract_value_inr"],
            completion_date=co_data["completion_date"],
            warranty_months=warranty_months,
            warranty_expiry=expiry.isoformat(),
            status="active" if expiry >= date.today() else "expired",
            is_synthetic=co_data.get("is_synthetic", True),
        ))
        loaded["contracts"] += 1

        device_count = entry.get("sensor_device_count", 0)
        if device_count >= 1:
            await _repo(request).upsert_sensor_cluster(gh[:6], "pothole")
            loaded["clusters"] += 1

    return {"status": "success", "loaded": loaded}
