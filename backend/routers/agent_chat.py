import re

from fastapi import APIRouter

from agent.tools import (
    check_warranty,
    get_area_complaints,
    get_complaint_status,
    get_contractor_ledger,
    get_my_complaints,
    ping,
    submit_complaint,
    vote_on_complaint,
)
from models.data_models import ChatRequest

router = APIRouter()

ALLOWED_TOOLS = {
    "citizen": [
        ping,
        submit_complaint,
        get_complaint_status,
        vote_on_complaint,
        get_area_complaints,
        get_contractor_ledger,
        check_warranty,
        get_my_complaints,
    ],
    "moderator": [
        ping,
        get_complaint_status,
        get_area_complaints,
        get_contractor_ledger,
        get_my_complaints,
    ],
    "admin": [
        ping,
        submit_complaint,
        get_complaint_status,
        vote_on_complaint,
        get_area_complaints,
        get_contractor_ledger,
        check_warranty,
        get_my_complaints,
    ],
}


@router.post("/chat")
async def agent_chat(req: ChatRequest):
    message = (req.message or "").strip()
    text = message.lower()
    anon_id = req.anon_id or "anon_chat_default"
    lat = float(req.lat or 12.9716)
    lng = float(req.lng or 77.5946)

    def finish(action: str, result: dict):
        if result.get("success"):
            return {"status": "success", "action": action, "data": result.get("data", {})}
        return {"status": "error", "action": action, "data": {}, "message": result.get("message", "Tool failed")}

    def complaint_type_from_text() -> str:
        if "no water" in text or "water" in text:
            return "no_water"
        if "garbage" in text or "trash" in text or "waste" in text:
            return "garbage"
        if "streetlight" in text or "street light" in text or "light broken" in text:
            return "street_light"
        if "drain" in text or "sewage" in text or "overflow" in text:
            return "drain"
        if "pothole" in text or "road" in text:
            return "pothole"
        return "other"

    try:
        complaint_id = req.complaint_id
        if not complaint_id:
            match = re.search(r"\bcmp_[a-zA-Z0-9_:-]+", message)
            if match:
                complaint_id = match.group(0)

        if req.vote_type or "corroborate" in text or "dispute" in text or "vote" in text:
            result = await vote_on_complaint(
                anon_id=anon_id,
                complaint_id=complaint_id or "",
                vote_type=req.vote_type or ("dispute" if "dispute" in text else "corroborate"),
            )
            return finish("vote_on_complaint", result)

        if complaint_id and ("status" in text or "check" in text or "complaint" in text):
            result = await get_complaint_status(complaint_id)
            return finish("get_complaint_status", result)

        if "my complaint" in text or "my grievances" in text:
            result = await get_my_complaints(anon_id)
            return finish("get_my_complaints", result)

        if any(word in text for word in ("contractor", "ledger", "accountability", "breach", "responsible")):
            result = await get_contractor_ledger(req.city or "Bengaluru")
            return finish("get_contractor_ledger", result)

        if "warranty" in text:
            result = await check_warranty(lat, lng)
            return finish("check_warranty", result)

        if any(phrase in text for phrase in ("near me", "show complaints", "community", "what's happening", "whats happening", "area")):
            result = await get_area_complaints(lat, lng, req.radius_km or 2.0)
            return finish("get_area_complaints", result)

        if any(word in text for word in ("pothole", "water", "garbage", "trash", "streetlight", "street light", "drain", "sewage", "broken", "overflow")):
            result = await submit_complaint(
                anon_id=anon_id,
                complaint_type=complaint_type_from_text(),
                lat=lat,
                lng=lng,
                description=message,
            )
            return finish("submit_complaint", result)

        result = await ping(message)
        return finish("ping", result)
    except Exception as e:
        return {"status": "error", "message": str(e)}
