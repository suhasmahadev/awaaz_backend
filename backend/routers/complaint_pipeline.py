import asyncio
import json
import os
import time
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.localization import (
    format_response,
    generate_voice,
    normalize_language,
    translate_text,
)

router = APIRouter()
COMPLAINT_TYPES = {"pothole", "no_water", "garbage", "drain", "street_light", "other"}
SEVERITIES = {"low", "medium", "high"}


class PipelineRequest(BaseModel):
    message: str
    anon_id: str
    lat: float = 12.9716
    lng: float = 77.5946
    language: str = "en"


class ConfirmRequest(BaseModel):
    anon_id: str
    complaint_preview: dict
    language: str = "en"


def sse(event: str, data: dict) -> str:
    return f"data: {json.dumps({'event': event, 'payload': data}, default=str)}\n\n"


def _fallback_validation(message: str) -> dict[str, Any]:
    text = (message or "").lower()
    has_injury = any(word in text for word in ("hurt", "injury", "injured", "accident", "fell"))

    if any(word in text for word in ("pothole", "road", "damaged road", "broken road")):
        complaint_type = "pothole"
        infrastructure_type = "road"
    elif any(word in text for word in ("water", "no water", "leaking", "pipeline")):
        complaint_type = "no_water"
        infrastructure_type = "water"
    elif any(word in text for word in ("garbage", "trash", "waste", "dirty", "smell")):
        complaint_type = "garbage"
        infrastructure_type = "waste"
    elif any(word in text for word in ("drain", "sewage", "flooded", "overflow")):
        complaint_type = "drain"
        infrastructure_type = "drainage"
    elif any(word in text for word in ("streetlight", "street light", "light")):
        complaint_type = "street_light"
        infrastructure_type = "lighting"
    else:
        complaint_type = "other"
        infrastructure_type = "unknown"

    civic_words = (
        "pothole",
        "road",
        "water",
        "garbage",
        "drain",
        "light",
        "sewage",
        "broken",
        "damaged",
        "leaking",
        "flooded",
        "dirty",
        "repair",
        "fix",
        "hurt",
        "injury",
    )
    is_genuine = any(word in text for word in civic_words)
    severity = "high" if has_injury else "medium" if is_genuine else "low"

    return {
        "is_genuine": is_genuine,
        "complaint_type": complaint_type,
        "severity": severity,
        "severity_reason": "Injury signal mentioned" if has_injury else "Civic issue keywords detected",
        "infrastructure_type": infrastructure_type,
        "has_injury_signal": has_injury,
        "confidence_in_classification": 0.7 if is_genuine else 0.35,
    }


async def _classify_with_gemini(message: str) -> dict[str, Any]:
    if not os.environ.get("GOOGLE_API_KEY"):
        return _fallback_validation(message)

    validation_prompt = f"""
Analyze this civic complaint message. Respond ONLY in JSON, no markdown.

Message: {json.dumps(message)}

Return:
{{
  "is_genuine": true,
  "complaint_type": "pothole|no_water|garbage|drain|street_light|other",
  "severity": "low|medium|high",
  "severity_reason": "one line explanation",
  "infrastructure_type": "road|water|waste|drainage|lighting|unknown",
  "has_injury_signal": true,
  "confidence_in_classification": 0.0
}}
"""

    try:
        import google.generativeai as genai

        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        model = genai.GenerativeModel("gemini-2.5-flash")
        resp = await asyncio.to_thread(model.generate_content, validation_prompt)
        raw = (resp.text or "").strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return _fallback_validation(message)


def _date_value(value: Any):
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


@router.post("/pipeline/analyze")
async def analyze_complaint(req: PipelineRequest, request: Request):
    pool = request.app.state.pool
    user_language = normalize_language(req.language)
    english_message = await translate_text(
        req.message,
        target_language="en",
        source_language=user_language,
    )
    english_message = english_message or req.message

    from repos.repo import Repo
    from services.service import Service
    from utils.confidence import SIGNAL_WEIGHTS, calculate_confidence
    from utils.geo import coords_to_geohash, find_nearest_asset_geohash

    svc = Service(Repo(pool))

    async def stream():
        yield sse("pipeline_start", {"message": req.message, "ts": time.time()})
        await asyncio.sleep(0.05)

        yield sse(
            "agent_start",
            {
                "agent": "validation",
                "label": "Validation Agent",
                "description": "Checking if this is a genuine civic complaint",
            },
        )

        validation_lines = [
            "Reading complaint text...",
            "Checking civic infrastructure keywords...",
            "Assessing severity signals...",
            "Verifying complaint pattern...",
        ]
        for line in validation_lines:
            yield sse("agent_token", {"agent": "validation", "text": line})
            await asyncio.sleep(0.3)

        fallback = _fallback_validation(english_message)
        validation = await _classify_with_gemini(english_message)
        is_genuine = validation.get("is_genuine")
        if not isinstance(is_genuine, bool):
            is_genuine = fallback["is_genuine"]
        has_injury = validation.get("has_injury_signal")
        if not isinstance(has_injury, bool):
            has_injury = fallback["has_injury_signal"]
        complaint_type = str(validation.get("complaint_type", fallback["complaint_type"])).lower()
        if complaint_type not in COMPLAINT_TYPES:
            complaint_type = fallback["complaint_type"]
        severity = str(validation.get("severity", fallback["severity"])).lower()
        if severity not in SEVERITIES:
            severity = fallback["severity"]
        infrastructure_type = validation.get("infrastructure_type") or fallback["infrastructure_type"]

        checks = [
            {"label": "Genuine civic complaint", "pass": is_genuine},
            {"label": f"Infrastructure type: {infrastructure_type}", "pass": True},
            {"label": f"Severity: {severity.upper()}", "pass": True},
        ]
        if has_injury:
            checks.append({"label": "Injury signal detected", "pass": True})

        yield sse(
            "agent_done",
            {
                "agent": "validation",
                "result": {
                    "is_genuine": is_genuine,
                    "checks": checks,
                    "complaint_type": complaint_type,
                    "severity": severity,
                },
            },
        )
        await asyncio.sleep(0.1)

        if not is_genuine:
            yield sse(
                "pipeline_done",
                {
                    "ready_to_post": False,
                    "reason": "Message does not appear to be a genuine civic complaint.",
                },
            )
            return

        yield sse(
            "agent_start",
            {
                "agent": "structuring",
                "label": "Structuring Agent",
                "description": "Building a complete complaint record",
            },
        )

        structuring_lines = [
            "Mapping complaint type to infrastructure category...",
            "Checking asset registry at given coordinates...",
            "Looking up active contracts near location...",
            "Checking warranty status...",
        ]
        for line in structuring_lines:
            yield sse("agent_token", {"agent": "structuring", "text": line})
            await asyncio.sleep(0.35)

        geohashes = find_nearest_asset_geohash(req.lat, req.lng)
        asset = await svc.repo.find_nearest_asset(geohashes)
        contract = None
        warranty_breach = False
        breach_value = 0
        contractor_name = None

        if asset:
            contract = await svc.repo.get_contract_by_asset(asset["id"])
            if contract:
                expiry = _date_value(contract.get("warranty_expiry"))
                if expiry and expiry >= date.today():
                    warranty_breach = True
                    breach_value = int(contract.get("contract_value_inr") or 0)
                    contractor = await svc.repo.get_contractor(contract["contractor_id"])
                    if contractor:
                        contractor_name = contractor["name"]

        structured = {
            "complaint_type": complaint_type,
            "description": english_message,
            "user_language": user_language,
            "severity": severity,
            "lat": req.lat,
            "lng": req.lng,
            "geohash": coords_to_geohash(req.lat, req.lng, 7),
            "asset_found": asset is not None,
            "asset_type": asset["asset_type"] if asset else None,
            "contract_found": contract is not None,
            "contract_number": contract["contract_number"] if contract else None,
            "warranty_breach": warranty_breach,
            "breach_value_inr": breach_value,
            "contractor_name": contractor_name,
            "has_injury_signal": has_injury,
        }

        yield sse(
            "agent_done",
            {
                "agent": "structuring",
                "result": {
                    "fields": [
                        {"label": "Type", "value": complaint_type.upper().replace("_", " ")},
                        {"label": "Severity", "value": severity.upper()},
                        {
                            "label": "Asset found",
                            "value": asset["asset_type"] if asset else "No tracked asset nearby",
                        },
                        {
                            "label": "Contract",
                            "value": contract["contract_number"] if contract else "No contract on record",
                        },
                        {
                            "label": "Warranty breach",
                            "value": f"YES - INR {breach_value // 100000}L exposed"
                            if warranty_breach
                            else "No",
                        },
                        {"label": "Contractor", "value": contractor_name or "Unknown"},
                    ],
                    "structured": structured,
                },
            },
        )
        await asyncio.sleep(0.1)

        yield sse(
            "agent_start",
            {
                "agent": "confidence",
                "label": "Confidence Agent",
                "description": "Calculating initial evidence confidence score",
            },
        )

        await asyncio.sleep(0.4)

        active_signals = ["single_report"]
        breakdown = calculate_confidence(active_signals, "preview")
        missing_signals = [
            key for key, weight in SIGNAL_WEIGHTS.items() if weight > 0 and key not in active_signals
        ]

        yield sse(
            "agent_done",
            {
                "agent": "confidence",
                "result": {
                    "score": breakdown.confidence,
                    "tier": breakdown.threshold_tier,
                    "active_signals": list(breakdown.signals.keys()),
                    "missing_signals": missing_signals[:4],
                    "message": "Score will rise with photo evidence, community votes, and corroborating reports.",
                },
            },
        )
        await asyncio.sleep(0.1)

        yield sse(
            "pipeline_done",
            {
                "ready_to_post": True,
                "complaint_preview": structured,
                "confidence": breakdown.confidence,
                "confidence_tier": breakdown.threshold_tier,
                "anon_id": req.anon_id,
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/pipeline/confirm")
async def confirm_complaint(req: ConfirmRequest, request: Request):
    pool = request.app.state.pool

    from repos.repo import Repo
    from services.service import Service

    svc = Service(Repo(pool))
    preview = req.complaint_preview or {}
    user_language = normalize_language(req.language or preview.get("user_language"))
    description_en = await translate_text(
        preview.get("description", ""),
        target_language="en",
        source_language=user_language,
    )
    result = await svc.submit_complaint(
        anon_id=req.anon_id,
        complaint_type=preview.get("complaint_type", "pothole"),
        lat=preview.get("lat", 12.9716),
        lng=preview.get("lng", 77.5946),
        description=description_en,
    )
    agent_json = {"status": "success", "action": "complaint_created", "data": result}
    text_response = format_response(agent_json, user_language)
    voice = await generate_voice(text_response, user_language)
    complaint_id = result.get("complaint_id") or result.get("id")
    payload = {
        "grievance_id": complaint_id,
        "complaint_id": complaint_id,
        "text_response": voice["text"],
        "audio_url": voice["audio_url"],
        **{k: v for k, v in result.items() if k not in {"complaint_id", "id"}},
    }
    return {"success": True, "data": payload}
