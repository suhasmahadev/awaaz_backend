import json
import logging
import os

import google.generativeai as genai

from constants import AGENT_MODEL

logger = logging.getLogger(__name__)


async def summarize_complaint(text: str) -> dict:
    try:
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY/GEMINI_API_KEY not configured")

        genai.configure(api_key=api_key)
        model_name = os.getenv("GEMINI_SUMMARY_MODEL", AGENT_MODEL)
        model = genai.GenerativeModel(model_name)
        prompt = f"""Return ONLY valid JSON with:
{{
  "summary": "2-sentence civic complaint summary",
  "priority": "critical|high|medium|low",
  "category": "short category",
  "risk_reason": "one line reason",
  "recommended_action": "specific admin action"
}}

Complaint:
{text}
"""
        response = await model.generate_content_async(prompt)
        raw = (getattr(response, "text", "") or "").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
        priority = str(parsed.get("priority") or "medium").lower()
        if priority not in {"critical", "high", "medium", "low"}:
            priority = "medium"
        return {
            "summary": parsed.get("summary") or text or "No description",
            "priority": priority,
            "category": parsed.get("category") or "civic",
            "risk_level": priority,
            "risk_reason": parsed.get("risk_reason") or "Gemini classified this complaint for admin review",
            "recommended_action": parsed.get("recommended_action") or "Inspect site manually",
            "model": model_name,
            "provider": "Google Gemini",
        }
    except Exception as exc:
        logger.error("Gemini summarization failed: %s", exc, exc_info=True)
        fallback_text = text or "No description"
        return {
            "summary": fallback_text,
            "priority": "medium",
            "category": "civic",
            "risk_level": "medium",
            "risk_reason": "Manual review needed - Gemini unavailable",
            "recommended_action": "Inspect site manually",
            "model": os.getenv("GEMINI_SUMMARY_MODEL", AGENT_MODEL),
            "provider": "Google Gemini",
        }
