import time
from typing import Optional

_pool = None


def set_pool(pool):
    global _pool
    _pool = pool


async def _svc():
    from repos.repo import Repo
    from services.service import Service
    return Service(Repo(_pool))


async def ping(message: str) -> dict:
    return {"success": True, "data": {"echo": message, "status": "pipeline_ok"}}


async def submit_complaint(
    anon_id: str,
    complaint_type: str,
    lat: float,
    lng: float,
    description: str = "",
) -> dict:
    try:
        svc = await _svc()
        result = await svc.submit_complaint(anon_id, complaint_type, lat, lng, description)
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "message": str(e)}


async def get_complaint_status(complaint_id: str) -> dict:
    try:
        svc = await _svc()
        complaint = await svc.repo.get_complaint(complaint_id)
        if not complaint:
            return {"success": False, "message": "Complaint not found"}
        return {"success": True, "data": dict(complaint)}
    except Exception as e:
        return {"success": False, "message": str(e)}


async def vote_on_complaint(
    anon_id: str,
    complaint_id: str,
    vote_type: str,
) -> dict:
    try:
        svc = await _svc()
        result = await svc.cast_vote(anon_id, complaint_id, vote_type)
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "message": str(e)}


async def get_area_complaints(
    lat: float,
    lng: float,
    radius_km: float = 2.0,
) -> dict:
    try:
        svc = await _svc()
        result = await svc.get_area_complaints(lat, lng, radius_km)
        return {"success": True, "data": {"complaints": result, "count": len(result)}}
    except Exception as e:
        return {"success": False, "message": str(e)}


async def get_contractor_ledger(city: str = "Bengaluru") -> dict:
    try:
        svc = await _svc()
        result = await svc.repo.list_contractors(city)
        return {"success": True, "data": {"contractors": [dict(r) for r in result]}}
    except Exception as e:
        return {"success": False, "message": str(e)}


async def check_warranty(lat: float, lng: float) -> dict:
    try:
        svc = await _svc()
        from utils.geo import find_nearest_asset_geohash
        geohashes = find_nearest_asset_geohash(lat, lng)
        asset = await svc.repo.find_nearest_asset(geohashes)
        if not asset:
            return {
                "success": True,
                "data": {
                    "asset_found": False,
                    "message": "No tracked infrastructure at this location",
                },
            }
        contract = await svc.repo.get_contract_by_asset(asset["id"])
        if not contract:
            return {
                "success": True,
                "data": {
                    "asset_found": True,
                    "contract_found": False,
                    "asset": dict(asset),
                },
            }
        from datetime import date
        expiry = contract["warranty_expiry"]
        in_warranty = expiry >= date.today() if expiry else False
        return {
            "success": True,
            "data": {
                "asset": dict(asset),
                "contract_number": contract["contract_number"],
                "contractor_id": contract["contractor_id"],
                "warranty_expiry": str(expiry),
                "in_warranty": in_warranty,
                "breach_possible": in_warranty,
            },
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


async def get_my_complaints(anon_id: str) -> dict:
    try:
        svc = await _svc()
        result = await svc.repo.list_complaints_by_anon(anon_id)
        return {"success": True, "data": {"complaints": [dict(r) for r in result]}}
    except Exception as e:
        return {"success": False, "message": str(e)}
