from pathlib import Path
from typing import Tuple


class FileValidationError(Exception):
    pass


def validate_file_content(file_bytes: bytes, filename: str, max_size_bytes: int) -> Tuple[str, str]:
    """
    Validates file size, extension, and verifies true binary content against magic bytes signatures.
    Rejects disguised executables, scripts, or corrupted files.
    Returns (cleaned_extension, detected_mime_type).
    """
    if len(file_bytes) == 0:
        raise FileValidationError("File is empty (0 bytes).")

    if len(file_bytes) > max_size_bytes:
        raise FileValidationError(
            f"File exceeds maximum allowed size of {max_size_bytes / (1024 * 1024):.1f} MB."
        )

    ext = Path(filename).suffix.lower()

    # Reject Windows PE executables explicitly
    if file_bytes.startswith(b"MZ"):
        raise FileValidationError("Executable files (PE/MZ format) are strictly forbidden.")

    # Reject ELF Linux binaries
    if file_bytes.startswith(b"\x7fELF"):
        raise FileValidationError("Executable binaries (ELF format) are strictly forbidden.")

    # Content signature inspection
    if ext == ".pdf":
        if not file_bytes.startswith(b"%PDF-"):
            raise FileValidationError("File content does not match genuine PDF magic signature.")
        mime = "application/pdf"

    elif ext in [".jpg", ".jpeg"]:
        if not file_bytes.startswith(b"\xff\xd8\xff"):
            raise FileValidationError("File content does not match genuine JPEG magic signature.")
        mime = "image/jpeg"

    elif ext == ".png":
        if not file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FileValidationError("File content does not match genuine PNG magic signature.")
        mime = "image/png"

    elif ext in [".zip", ".xlsx"]:
        # ZIP and XLSX (OpenXML format) must start with PK zip signature
        if not (file_bytes.startswith(b"PK\x03\x04") or file_bytes.startswith(b"PK\x05\x06")):
            raise FileValidationError(f"File content does not match genuine {ext.upper()} archive signature.")
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if ext == ".xlsx" else "application/zip"

    elif ext == ".xml":
        # Check text starts with XML declaration or root XML tag
        stripped = file_bytes.lstrip(b"\xef\xbb\xbf \t\r\n")  # Strip UTF-8 BOM and leading whitespace
        if not (stripped.startswith(b"<?xml") or stripped.startswith(b"<")):
            raise FileValidationError("File content is not valid XML markup.")
        mime = "application/xml"

    else:
        raise FileValidationError(f"File extension '{ext}' is not supported. Allowed: PDF, JPG, PNG, XLSX, XML, ZIP.")

    return ext, mime
