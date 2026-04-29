from datetime import date, datetime

from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["community"])


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _public_complaint(c: dict, fallback_lat: float, fallback_lng: float) -> dict:
    lat = c.get("lat") if c.get("lat") is not None else fallback_lat
    lng = c.get("lng") if c.get("lng") is not None else fallback_lng
    complaint_type = c.get("complaint_type") or c.get("category") or "other"
    return {
        "id": c.get("id"),
        "grievance_id": c.get("id"),
        "title": complaint_type.replace("_", " ").title(),
        "description": c.get("description") or "",
        "complaint_type": complaint_type,
        "category": complaint_type,
        "urgency": c.get("status") or "unverified",
        "geo": {"geohash": c.get("geohash")},
        "lat": lat,
        "lng": lng,
        "media_url": c.get("media_url"),
        "status": c.get("status"),
        "confidence_score": c.get("confidence_score") or 0,
        "confidence_signals": c.get("confidence_signals") or {},
        "warranty_breach": c.get("warranty_breach") or False,
        "breach_value_inr": c.get("breach_value_inr") or 0,
        "vote_count": c.get("vote_count") or 0,
        "report_count": c.get("report_count") or 1,
        "created_at": _json_value(c.get("created_at")),
        "hash": c.get("id"),
        "contractor": None,
    }


@router.get("/community")
async def community(
    request: Request,
    lat: float = Query(12.9716),
    lng: float = Query(77.5946),
    all: bool = Query(False),
):
    try:
        from utils.geo import coords_to_geohash

        if all:
            complaints = await request.app.state.repo.list_all_complaints()
        else:
            geohash_prefix = coords_to_geohash(lat, lng, 5)
            complaints = await request.app.state.repo.list_complaints_by_area(geohash_prefix)
        items = [_public_complaint(c, lat, lng) for c in complaints]
        return {"status": "success", "complaints": items, "count": len(items)}
    except Exception as exc:
        return {"status": "success", "complaints": [], "count": 0, "error": str(exc)}
