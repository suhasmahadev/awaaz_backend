import time
import uuid
from pathlib import Path

import aiofiles
from fastapi import UploadFile

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


async def save_upload(file: UploadFile, base_url: str, upload_dir: Path) -> str:
    try:
      content_type = (file.content_type or "").lower()
      if content_type not in ALLOWED_IMAGE_TYPES:
          raise ValueError("Only image uploads are supported")

      safe_suffix = Path(file.filename or "").suffix.lower() or ALLOWED_IMAGE_TYPES[content_type]
      if safe_suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
          safe_suffix = ALLOWED_IMAGE_TYPES[content_type]

      upload_dir.mkdir(parents=True, exist_ok=True)
      filename = f"media_{int(time.time() * 1000)}_{uuid.uuid4().hex[:10]}{safe_suffix}"
      destination = upload_dir / filename

      async with aiofiles.open(destination, "wb") as out:
          while True:
              chunk = await file.read(1024 * 1024)
              if not chunk:
                  break
              await out.write(chunk)

      return f"{base_url.rstrip('/')}/uploads/{filename}"
    except Exception:
      raise
