import os
import re
import uuid
from pathlib import Path
from app.core.config import settings
from app.integrations.storage.base import StorageBackend


def sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^\w\.-]", "_", Path(filename).name)
    return cleaned or "unnamed_file"


class LocalStorageBackend(StorageBackend):
    """
    Local filesystem storage implementation for MVP.
    Saves files in structured directory tree scoped by organization_id.
    """

    def __init__(self, base_dir: str = settings.UPLOAD_DIR):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, stored_path: str) -> Path:
        resolved = (self.base_dir / stored_path).resolve()
        # Prevent path traversal attacks
        if not str(resolved).startswith(str(self.base_dir)):
            raise ValueError("Attempted path traversal violation.")
        return resolved

    async def save(self, file_bytes: bytes, filename: str, organization_id: str) -> str:
        safe_name = sanitize_filename(filename)
        file_uuid = uuid.uuid4().hex[:12]
        relative_path = Path(organization_id) / f"{file_uuid}_{safe_name}"
        full_path = self._resolve_safe_path(str(relative_path))

        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(file_bytes)

        # Store as POSIX-compliant relative string
        return str(relative_path).replace("\\", "/")

    async def get(self, stored_path: str) -> bytes:
        full_path = self._resolve_safe_path(stored_path)
        if not full_path.exists():
            raise FileNotFoundError(f"File {stored_path} does not exist.")
        with open(full_path, "rb") as f:
            return f.read()

    async def delete(self, stored_path: str) -> bool:
        full_path = self._resolve_safe_path(stored_path)
        if full_path.exists():
            full_path.unlink()
            return True
        return False

    async def get_url(self, stored_path: str) -> str:
        # Local endpoint downloads through API route
        return f"/api/v1/files/download?path={stored_path}"
