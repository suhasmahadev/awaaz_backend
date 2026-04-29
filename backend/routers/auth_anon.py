import hashlib

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class AnonRequest(BaseModel):
    fingerprint: str


def generate_anon_id(fingerprint: str) -> str:
    return "ANON-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


@router.post("/auth/anon")
async def create_or_get_anon(req: AnonRequest, request: Request):
    fingerprint = (req.fingerprint or "").strip()
    if not fingerprint:
        raise HTTPException(status_code=422, detail="fingerprint must be a non-empty string")

    pool = request.app.state.pool

    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT anon_id FROM anon_users WHERE fingerprint = $1",
            fingerprint,
        )

        if existing:
            await conn.execute(
                """
                INSERT INTO anonymous_reporters (anon_id)
                VALUES ($1)
                ON CONFLICT DO NOTHING
                """,
                existing["anon_id"],
            )
            return {"anon_id": existing["anon_id"]}

        anon_id = generate_anon_id(fingerprint)
        row = await conn.fetchrow(
            """
            INSERT INTO anon_users (anon_id, fingerprint)
            VALUES ($1, $2)
            ON CONFLICT (fingerprint)
            DO UPDATE SET fingerprint = EXCLUDED.fingerprint
            RETURNING anon_id
            """,
            anon_id,
            fingerprint,
        )

        await conn.execute(
            """
            INSERT INTO anonymous_reporters (anon_id)
            VALUES ($1)
            ON CONFLICT DO NOTHING
            """,
            row["anon_id"],
        )

    return {"anon_id": row["anon_id"]}
