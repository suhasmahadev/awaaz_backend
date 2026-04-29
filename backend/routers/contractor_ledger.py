"""
Public contractor ledger ??? no auth required.
This is the economic pressure layer. Accuracy is non-negotiable.
All fields are null-safe. failure_score=0.0 for contractors with no complaints.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)
router = APIRouter()


def _svc(request: Request):
    return request.app.state.service

def _repo(request: Request):
    return request.app.state.repo


@router.get("")
async def get_ledger(
    city: Optional[str] = Query(None),
    request: Request = None,
):
    """
    Returns all contractors sorted by failure_score DESC.
    Public endpoint ??? no authentication required.

    Each entry includes: name, active_contracts, active_breach_count,
    total_breach_value_inr, failure_score. All values are null-safe.
    """
    try:
        data = await _svc(request).get_ledger(city=city)
        return {
            "contractors": data,
            "count": len(data),
            "sorted_by": "failure_score DESC",
        }
    except Exception as exc:
        logger.error("ledger GET failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/feed")
async def get_ledger_feed(request: Request):
    """
    Machine-readable JSON feed for media/RTI consumers.
    Sorted by total_breach_value_inr DESC.
    Includes: generated_at, total_contractors, total_breach_value_inr.
    """
    from datetime import datetime, timezone
    try:
        data = await _svc(request).get_ledger()
        data_sorted = sorted(data, key=lambda x: x.get("total_breach_value_inr", 0), reverse=True)
        total_exposure = sum(d.get("total_breach_value_inr", 0) for d in data_sorted)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_contractors": len(data_sorted),
            "total_breach_value_inr": total_exposure,
            "feed": data_sorted,
        }
    except Exception as exc:
        logger.error("ledger/feed failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/city/{city}")
async def ledger_by_city(city: str, request: Request):
    """Contractors filtered by city, sorted by failure_score DESC."""
    try:
        data = await _svc(request).get_ledger(city=city)
        return {"city": city, "contractors": data, "count": len(data)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{contractor_id}")
async def get_contractor_profile(contractor_id: str, request: Request):
    """
    Full contractor profile with breach history.
    Breach history items include: ward (not exact GPS), complaint_type,
    breach_value_inr, days_since_completion, warranty_remaining_days (negative = overdue),
    confidence_score, status.
    Sorted by confidence_score DESC, then days_since_completion DESC.
    """
    try:
        profile = await _svc(request).get_contractor_profile(contractor_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Contractor not found")
        return profile
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ledger/%s failed: %s", contractor_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))
