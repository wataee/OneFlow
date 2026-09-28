import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_auth_registration_and_login(client: AsyncClient):
    # 1. Register new organization & user
    reg_payload = {
        "email": "cfo@company.kz",
        "password": "StrongPassword123!",
        "full_name": "Бауржан Сейфуллин",
        "organization_name": "ТОО Байтерек Финанс",
        "business_role": "ACCOUNTANT",
    }
    reg_resp = await client.post("/api/v1/auth/register", json=reg_payload)
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert "access_token" in reg_data
    assert "refresh_token" in reg_resp.cookies

    # 2. Login
    login_payload = {
        "email": "cfo@company.kz",
        "password": "StrongPassword123!",
    }
    login_resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    access_token = login_data["access_token"]
    assert "refresh_token" in login_resp.cookies

    # 3. Call protected endpoint /me
    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "cfo@company.kz"
    assert me_data["role"] == "admin"
    assert me_data["business_role"] == "ACCOUNTANT"


@pytest.mark.asyncio
async def test_auth_unauthorized_and_invalid_token(client: AsyncClient):
    # No token -> 401
    resp = await client.get("/api/v1/tasks/")
    assert resp.status_code == 401

    # Invalid token -> 401
    resp_invalid = await client.get("/api/v1/tasks/", headers={"Authorization": "Bearer invalid_garbage_token"})
    assert resp_invalid.status_code == 401


@pytest.mark.asyncio
async def test_auth_refresh_token_cookie(client: AsyncClient):
    # Register to get cookie
    reg_resp = await client.post("/api/v1/auth/register", json={
        "email": "accountant@fin.kz",
        "password": "StrongPassword123!",
        "full_name": "Камила Нурлан",
        "organization_name": "ТОО ФинЭксперт",
    })
    assert reg_resp.status_code == 201
    refresh_cookie = reg_resp.cookies.get("refresh_token")
    assert refresh_cookie is not None

    # Call /refresh with cookie
    refresh_resp = await client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh_cookie})
    assert refresh_resp.status_code == 200
    new_data = refresh_resp.json()
    assert "access_token" in new_data
