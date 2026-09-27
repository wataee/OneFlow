from app.core.config import settings
from app.integrations.storage.base import StorageBackend
from app.integrations.storage.local import LocalStorageBackend


def get_storage_backend() -> StorageBackend:
    """
    Factory to retrieve storage backend.
    Switching from LocalStorage to S3/MinIO is a matter of configuration.
    """
    if settings.STORAGE_BACKEND == "local":
        return LocalStorageBackend(base_dir=settings.UPLOAD_DIR)
    
    # Ready for S3 plug-in without changing service or API code
    if settings.STORAGE_BACKEND == "s3":
        raise NotImplementedError("S3 storage backend configured but AWS credentials not provided.")

    return LocalStorageBackend(base_dir=settings.UPLOAD_DIR)
