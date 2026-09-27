import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_file_upload_valid_formats(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]

    # 1. Valid PDF upload (with genuine %PDF- magic bytes)
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    pdf_resp = await client.post(
        "/api/v1/files/upload",
        headers=headers,
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
    )
    assert pdf_resp.status_code == 201
    pdf_data = pdf_resp.json()
    assert pdf_data["filename"] == "invoice.pdf"
    assert pdf_data["mime_type"] == "application/pdf"
    file_id = pdf_data["id"]

    # 2. Download verification
    dl_resp = await client.get(f"/api/v1/files/{file_id}/download", headers=headers)
    assert dl_resp.status_code == 200
    assert dl_resp.content == pdf_bytes

    # 3. Soft delete verification
    del_resp = await client.delete(f"/api/v1/files/{file_id}", headers=headers)
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["deleted_at"] is not None

    # 4. Subsequent download of soft-deleted file returns 404
    dl_deleted = await client.get(f"/api/v1/files/{file_id}/download", headers=headers)
    assert dl_deleted.status_code == 404


@pytest.mark.asyncio
async def test_file_upload_disguised_executable_rejected(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]

    # PE Executable masquerading as a PDF ("invoice.pdf" with "MZ" header)
    fake_pdf = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00This is a Windows executable binary"
    resp = await client.post(
        "/api/v1/files/upload",
        headers=headers,
        files={"file": ("invoice.pdf", fake_pdf, "application/pdf")},
    )
    assert resp.status_code == 400
    err_detail = resp.json()["detail"]
    assert "executable" in err_detail.lower() or "signature" in err_detail.lower()
