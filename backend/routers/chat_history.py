from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ChatSave(BaseModel):
    anon_id: str
    role: str
    message: str


@router.post("/chat/save")
async def save_chat(req: ChatSave, request: Request):
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO chat_history (anon_id, role, message)
            VALUES ($1, $2, $3)
            """,
            req.anon_id,
            req.role,
            req.message,
        )

    return {"success": True}


@router.get("/chat/history/{anon_id}")
async def get_history(anon_id: str, request: Request):
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, message, created_at
            FROM chat_history
            WHERE anon_id = $1
            ORDER BY created_at ASC
            """,
            anon_id,
        )

    return {
        "messages": [
            {
                "role": r["role"],
                "message": r["message"],
                "timestamp": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }
