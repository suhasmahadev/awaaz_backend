import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from services.storage_service import save_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/media", tags=["media"])


@router.post("/upload")
async def upload_media(request: Request, file: UploadFile = File(...)):
    try:
        if not file or not file.filename:
            raise HTTPException(status_code=422, detail="file is required")
        upload_dir = Path(__file__).parent.parent / "uploads"
        media_url = await save_upload(file, str(request.base_url), upload_dir)
        return {"media_url": media_url}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("media upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Media upload failed")
