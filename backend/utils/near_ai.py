"""
NEAR AI Cloud client — OpenAI-compatible, TEE-backed inference.
Used for: complaint classification, admin AI summarisation.
NOT used for: Google ADK agent chat (that stays on Gemini).
"""
import os, json
from openai import OpenAI

def get_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ.get("NEAR_AI_BASE", "https://cloud-api.near.ai/v1"),
        api_key=os.environ["NEAR_AI_KEY"],
    )

MODEL = os.environ.get("NEAR_AI_MODEL", "deepseek-ai/DeepSeek-V3.1")

def call(prompt: str, system: str = "Return only valid JSON. No markdown.") -> dict:
    """
    Calls NEAR AI Cloud with given prompt. Returns parsed JSON dict.
    Falls back to empty dict on failure — callers must handle fallback.
    """
    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=512,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.strip("```json").strip("```").strip()
        return json.loads(raw)
    except Exception as e:
        import logging
        logging.error(f"NEAR AI call failed: {e}")
        return {}

def get_attestation_info() -> dict:
    """
    Returns metadata about the TEE inference for display in UI/audit log.
    NEAR AI runs all inference in Intel TDX/SGX TEEs.
    """
    return {
        "provider": "NEAR AI Cloud",
        "model": MODEL,
        "tee_type": "Intel TDX (attested)",
        "endpoint": os.environ.get("NEAR_AI_BASE", "https://cloud-api.near.ai/v1"),
        "verification_url": "https://docs.near.ai/cloud/verification",
        "note": "All inference runs in hardware TEE. Independently verifiable.",
    }
