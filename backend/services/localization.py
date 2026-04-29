"""Human-facing response, translation, and TTS helpers.

The agent/tool layer keeps returning strict JSON. This module turns that JSON
into citizen-facing text only after the logical action has completed.
"""
import asyncio
import base64
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
TTS_DIR = BACKEND_DIR / "static" / "tts"

STATUS_LABELS_EN = {
    "CREATED": "created",
    "UNVERIFIED": "created",
    "LOW_CONFIDENCE": "under review",
    "MEDIUM_CONFIDENCE": "being verified",
    "HIGH_CONFIDENCE": "verified",
    "RESOLVED": "resolved",
    "DISPUTED": "disputed",
}

STATUS_LABELS_KN = {
    "CREATED": "ದಾಖಲಾಗಿದೆ",
    "UNVERIFIED": "ದಾಖಲಾಗಿದೆ",
    "LOW_CONFIDENCE": "ಪರಿಶೀಲನೆಯಲ್ಲಿದೆ",
    "MEDIUM_CONFIDENCE": "ಚೆಕ್ ಆಗ್ತಿದೆ",
    "HIGH_CONFIDENCE": "ದೃಢವಾಗಿದೆ",
    "RESOLVED": "ಪರಿಹಾರವಾಗಿದೆ",
    "DISPUTED": "ವಿವಾದದಲ್ಲಿದೆ",
}


def normalize_language(language: Optional[str]) -> str:
    value = (language or "en").strip().lower()
    if value.startswith("kn") or "kannada" in value:
        return "kn"
    return "en"


def public_audio_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"/static/tts/{Path(path).name}"


def _status_key(status: Optional[str]) -> str:
    return (status or "CREATED").replace("-", "_").upper()


def display_status(status: Optional[str]) -> str:
    key = _status_key(status)
    return "CREATED" if key == "UNVERIFIED" else key


def _status_label(status: Optional[str], language: str) -> str:
    key = _status_key(status)
    labels = STATUS_LABELS_KN if normalize_language(language) == "kn" else STATUS_LABELS_EN
    return labels.get(key, status or "created")


def _complaint_id(data: dict) -> str:
    return (
        data.get("grievance_id")
        or data.get("complaint_id")
        or data.get("id")
        or data.get("complaint", {}).get("id")
        or ""
    )


def format_response(agent_json: dict, user_language: str = "en") -> str:
    """Convert strict agent/tool JSON into a natural user-facing response."""
    language = normalize_language(user_language)
    payload = agent_json or {}
    status = payload.get("status", "success")
    action = (payload.get("action") or "").lower()
    data = payload.get("data") or {}

    if status != "success":
        message = payload.get("message") or data.get("message") or "Something went wrong."
        if language == "kn":
            return f"ಅಯ್ಯೋ, ಸ್ವಲ್ಪ ಸಮಸ್ಯೆ ಆಯ್ತು. {message}"
        return f"Something went wrong: {message}"

    if action in {"complaint_created", "submit_complaint"}:
        grievance_id = _complaint_id(data)
        if language == "kn":
            if grievance_id:
                return f"ಸರಿ, ನಿಮ್ಮ ಸಮಸ್ಯೆ ದಾಖಲಾಯ್ತು. ಈ ಐಡಿ ಇಟ್ಟುಕೊಳ್ಳಿ: {grievance_id}"
            return "ಸರಿ, ನಿಮ್ಮ ಸಮಸ್ಯೆ ದಾಖಲಾಯ್ತು. ನಾವು ಇದನ್ನು ಟ್ರ್ಯಾಕ್ ಮಾಡ್ತೀವಿ."
        if grievance_id:
            return f"Your complaint is registered. Your ID is {grievance_id}."
        return "Your complaint is registered. We will track it from here."

    if action in {"complaint_history_item", "get_complaint_status"}:
        complaint = data.get("complaint") if isinstance(data.get("complaint"), dict) else data
        grievance_id = _complaint_id(complaint)
        status_label = _status_label(complaint.get("status"), language)
        if language == "kn":
            if grievance_id:
                return f"{grievance_id} ದೂರು ಈಗ {status_label}. ಅಪ್ಡೇಟ್ ನೋಡ್ಕೊಂಡಿರಿ."
            return f"ನಿಮ್ಮ ದೂರು ಈಗ {status_label}."
        if grievance_id:
            return f"Complaint {grievance_id} is currently {status_label}."
        return f"Your complaint is currently {status_label}."

    if action == "get_my_complaints":
        complaints = data.get("complaints") or []
        count = len(complaints)
        if language == "kn":
            return f"ನಿಮ್ಮ {count} ದೂರುಗಳು ಸಿಕ್ಕಿವೆ. ಒಂದೊಂದರ ಸ್ಥಿತಿ ಕೆಳಗೆ ಇದೆ."
        return f"I found {count} complaints from you. Their latest status is below."

    if action == "get_area_complaints":
        complaints = data.get("complaints") or []
        count = data.get("count", len(complaints))
        if language == "kn":
            return f"ನಿಮ್ಮ ಹತ್ತಿರ {count} ಸಾರ್ವಜನಿಕ ಸಮಸ್ಯೆಗಳು ಕಾಣ್ತಿವೆ."
        return f"I found {count} public issues near you."

    if action == "vote_on_complaint":
        if language == "kn":
            return "ನಿಮ್ಮ ಮತ ಸೇರಿತು. ದೂರುದ ವಿಶ್ವಾಸಾರ್ಹತೆ ಈಗ ಅಪ್ಡೇಟ್ ಆಗಿದೆ."
        return "Your vote is recorded. The complaint confidence has been updated."

    if action == "ping":
        echo = data.get("echo")
        if language == "kn":
            return f"ನಾನು ರೆಡಿ ಇದ್ದೀನಿ. {echo}" if echo else "ನಾನು ರೆಡಿ ಇದ್ದೀನಿ."
        return f"I am ready. {echo}" if echo else "I am ready."

    message = data.get("message") or payload.get("message")
    if message:
        return str(message)
    if language == "kn":
        return "ಸರಿ, ಕೆಲಸ ಆಯ್ತು."
    return "Done."


def _mostly_english(text: str) -> bool:
    letters = [ch for ch in text if not ch.isspace()]
    if not letters:
        return True
    ascii_count = sum(1 for ch in letters if ord(ch) < 128)
    return ascii_count / max(len(letters), 1) > 0.85


def _clean_model_text(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json|text)?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.removesuffix("```").strip()
    return cleaned


async def _translate_with_gemini(text: str, target_language: str, source_language: Optional[str]) -> Optional[str]:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None

    target_name = "Kannada" if normalize_language(target_language) == "kn" else "English"
    source_name = "auto-detected" if not source_language else normalize_language(source_language)
    prompt = (
        f"Translate this civic grievance text to {target_name}. "
        "Preserve IDs, place names, numbers, and complaint meaning. "
        "Return only the translated sentence, no markdown.\n\n"
        f"Source language: {source_name}\n"
        f"Text: {text}"
    )

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model_name = os.environ.get("GEMINI_TRANSLATION_MODEL", "gemini-2.5-flash")
        model = genai.GenerativeModel(model_name)
        response = await asyncio.to_thread(model.generate_content, prompt)
        translated = _clean_model_text(getattr(response, "text", "") or "")
        return translated or None
    except Exception as exc:
        logger.warning("Gemini translation failed: %s", exc)
        return None


def _fallback_to_english(text: str) -> str:
    lower = (text or "").lower()
    if any(word in lower for word in ("ಗುಂಡಿ", "ರಸ್ತೆ", "road", "pothole")):
        return "Citizen reported a pothole or damaged road near the selected location."
    if any(word in lower for word in ("ನೀರು", "water", "leak", "pipeline")):
        return "Citizen reported a water supply issue near the selected location."
    if any(word in lower for word in ("ಕಸ", "garbage", "trash", "waste")):
        return "Citizen reported a garbage or waste issue near the selected location."
    if any(word in lower for word in ("ಚರಂಡಿ", "drain", "sewage", "flood")):
        return "Citizen reported a drainage or sewage issue near the selected location."
    if any(word in lower for word in ("ಲೈಟ್", "ಬೆಳಕು", "streetlight", "street light")):
        return "Citizen reported a street light issue near the selected location."
    return "Citizen reported a civic issue near the selected location."


async def translate_text(
    text: Optional[str],
    target_language: str = "en",
    source_language: Optional[str] = None,
) -> Optional[str]:
    """Translate user text for storage/display. Complaints are stored in English."""
    if text is None:
        return None

    cleaned = text.strip()
    if not cleaned:
        return cleaned

    target = normalize_language(target_language)
    source = normalize_language(source_language) if source_language else None

    if source and source == target:
        if target == "en" and not _mostly_english(cleaned):
            pass
        else:
            return cleaned
    if target == "en" and _mostly_english(cleaned):
        return cleaned

    translated = await _translate_with_gemini(cleaned, target, source)
    if translated:
        return translated

    if target == "en":
        return _fallback_to_english(cleaned)
    return cleaned


async def _generate_with_google_tts(text: str, language: str, output_path: Path) -> bool:
    api_key = os.environ.get("GOOGLE_TTS_API_KEY") or os.environ.get("GOOGLE_CLOUD_TTS_API_KEY")
    if not api_key:
        return False

    language_code = "kn-IN" if language == "kn" else "en-IN"
    voice_name = os.environ.get("GOOGLE_TTS_KN_VOICE" if language == "kn" else "GOOGLE_TTS_EN_VOICE")
    voice = {"languageCode": language_code, "ssmlGender": "FEMALE"}
    if voice_name:
        voice["name"] = voice_name

    body = {
        "input": {"text": text},
        "voice": voice,
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 0.96},
    }
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(url, json=body)
        response.raise_for_status()
        audio_content = response.json().get("audioContent")
        if not audio_content:
            return False
        output_path.write_bytes(base64.b64decode(audio_content))
        return True
    except Exception as exc:
        logger.warning("Google TTS failed: %s", exc)
        return False


async def _generate_with_elevenlabs(text: str, language: str, output_path: Path) -> bool:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return False

    voice_id = (
        os.environ.get("ELEVENLABS_KN_VOICE_ID" if language == "kn" else "ELEVENLABS_EN_VOICE_ID")
        or os.environ.get("ELEVENLABS_VOICE_ID")
    )
    if not voice_id:
        return False

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    body = {
        "text": text,
        "model_id": os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
    }
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        output_path.write_bytes(response.content)
        return True
    except Exception as exc:
        logger.warning("ElevenLabs TTS failed: %s", exc)
        return False


async def generate_voice(text: str, language: str = "en") -> dict:
    """Generate high-quality voice when a TTS provider is configured."""
    language_code = normalize_language(language)
    spoken_text = (text or "").strip()
    if not spoken_text:
        return {"text": text or "", "audio_url": None}

    TTS_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{language_code}:{spoken_text}".encode("utf-8")).hexdigest()[:24]
    output_path = TTS_DIR / f"{language_code}_{digest}.mp3"
    if output_path.exists():
        return {"text": spoken_text, "audio_url": public_audio_url(str(output_path))}

    generated = False
    if language_code == "kn":
        generated = await _generate_with_google_tts(spoken_text, language_code, output_path)
        if not generated:
            generated = await _generate_with_elevenlabs(spoken_text, language_code, output_path)
    else:
        generated = await _generate_with_elevenlabs(spoken_text, language_code, output_path)
        if not generated:
            generated = await _generate_with_google_tts(spoken_text, language_code, output_path)

    return {
        "text": spoken_text,
        "audio_url": public_audio_url(str(output_path)) if generated else None,
    }
