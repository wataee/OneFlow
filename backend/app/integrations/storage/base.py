from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """
    Abstract storage backend interface for file uploads.
    Decouples local filesystem, S3, MinIO, or Google Cloud Storage.
    """

    @abstractmethod
    async def save(self, file_bytes: bytes, filename: str, organization_id: str) -> str:
        """Saves file bytes and returns stored relative path/identifier."""
        pass

    @abstractmethod
    async def get(self, stored_path: str) -> bytes:
        """Retrieves raw file bytes by stored path."""
        pass

    @abstractmethod
    async def delete(self, stored_path: str) -> bool:
        """Deletes file physically from storage."""
        pass

    @abstractmethod
    async def get_url(self, stored_path: str) -> str:
        """Returns direct or presigned URL for downloading the file."""
        pass
