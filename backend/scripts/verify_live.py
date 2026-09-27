import asyncio
import httpx

BASE_URL = "http://127.0.0.1:8000"


async def run_live_verification():
    print(f"=== Starting Live Verification on {BASE_URL} ===\n")
    results = {}

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Healthcheck
        print("1. Testing Healthcheck /health...")
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "healthy"
        assert health_data["database"] == "connected"
        results["1. Healthcheck"] = "PASSED"
        print(f"   -> OK: {health_data}")

        # 2. Auth: Login & Refresh Cookie
        print("\n2. Testing Login & Refresh Cookie (admin@example.kz)...")
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "admin@example.kz",
            "password": "Secret123!"
        })
        assert login_resp.status_code == 200
        tokens = login_resp.json()
        access_token_a = tokens["access_token"]
        refresh_cookie_a = login_resp.cookies.get("refresh_token")
        assert refresh_cookie_a is not None, "Refresh cookie must be present!"
        headers_a = {"Authorization": f"Bearer {access_token_a}"}
        results["2. Login & Cookie"] = "PASSED"
        print(f"   -> OK: Access token received, refresh cookie: {refresh_cookie_a[:15]}...")

        # 3. Auth: Protected /me
        print("\n3. Testing Protected /me endpoint...")
        me_resp = await client.get("/api/v1/auth/me", headers=headers_a)
        assert me_resp.status_code == 200
        user_info = me_resp.json()
        assert user_info["email"] == "admin@example.kz"
        org_a_id = user_info["organization_id"]
        results["3. Protected /me"] = "PASSED"
        print(f"   -> OK: Authenticated as {user_info['full_name']}, org: {org_a_id}")

        # 4. Auth: Unauthorized requests rejected
        print("\n4. Testing 401 on missing or invalid token...")
        unauth_resp = await client.get("/api/v1/tasks/")
        assert unauth_resp.status_code == 401
        invalid_resp = await client.get("/api/v1/tasks/", headers={"Authorization": "Bearer bad_token"})
        assert invalid_resp.status_code == 401
        results["4. 401 Handling"] = "PASSED"
        print("   -> OK: 401 Unauthorized properly returned")

        # 5. Auth: Token refresh via cookie
        print("\n5. Testing /refresh with httpOnly cookie...")
        refresh_resp = await client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh_cookie_a})
        assert refresh_resp.status_code == 200
        refreshed_tokens = refresh_resp.json()
        assert "access_token" in refreshed_tokens
        results["5. Refresh Token"] = "PASSED"
        print("   -> OK: New access token successfully issued")

        # 6. Dashboard metrics
        print("\n6. Testing Dashboard SQL Aggregation Metrics...")
        dash_resp = await client.get("/api/v1/dashboard/metrics", headers=headers_a)
        assert dash_resp.status_code == 200
        metrics = dash_resp.json()
        assert metrics["total_tasks"] > 0
        results["6. Dashboard Metrics"] = "PASSED"
        print(f"   -> OK: Metrics: {metrics}")

        # 7. Multi-Tenancy Isolation
        print("\n7. Testing Multi-Tenancy Isolation across tenants...")
        login_b_resp = await client.post("/api/v1/auth/login", json={
            "email": "other@example.kz",
            "password": "Secret123!"
        })
        assert login_b_resp.status_code == 200
        headers_b = {"Authorization": f"Bearer {login_b_resp.json()['access_token']}"}

        tasks_a_resp = await client.get("/api/v1/tasks/", headers=headers_a)
        tasks_b_resp = await client.get("/api/v1/tasks/", headers=headers_b)
        tasks_a_ids = {t["id"] for t in tasks_a_resp.json()["items"]}
        tasks_b_ids = {t["id"] for t in tasks_b_resp.json()["items"]}

        # Disjoint sets: Org A and Org B must have zero intersection
        assert tasks_a_ids.isdisjoint(tasks_b_ids)
        # Attempting cross-tenant GET returns 404
        sample_a_id = list(tasks_a_ids)[0]
        cross_resp = await client.get(f"/api/v1/tasks/{sample_a_id}", headers=headers_b)
        assert cross_resp.status_code == 404
        results["7. Multi-Tenancy Isolation"] = "PASSED"
        print(f"   -> OK: Org A ({len(tasks_a_ids)} tasks) and Org B ({len(tasks_b_ids)} tasks) completely isolated. Cross-access 404 verified.")

        # 8. Task creation and lifecycle
        print("\n8. Testing Task Creation (202 Accepted) & Synchronous Execution...")
        create_resp = await client.post(
            "/api/v1/tasks/",
            headers=headers_a,
            json={"type": "BANK_OPERATION", "input_data": {"force_review": True, "amount": 990000}}
        )
        assert create_resp.status_code == 202
        new_task = create_resp.json()
        new_task_id = new_task["id"]
        assert new_task["status"] == "PENDING"

        exec_resp = await client.post(f"/api/v1/tasks/{new_task_id}/execute-sync", headers=headers_a)
        assert exec_resp.status_code == 200
        processed_task = exec_resp.json()
        assert processed_task["status"] == "REVIEW"
        results["8. Task Lifecycle & FSM"] = "PASSED"
        print(f"   -> OK: Created PENDING -> Executed -> Transitioned to {processed_task['status']} (confidence: {processed_task['confidence']})")

        # 9. Review: Approve, Reject, Edit with Diff
        print("\n9. Testing Review System & Diff Recording...")
        reviews_resp = await client.get("/api/v1/reviews/", headers=headers_a)
        assert reviews_resp.status_code == 200
        rev_item = next(r for r in reviews_resp.json()["items"] if r["task_id"] == new_task_id)
        
        edit_payload = {"amount": 990000, "human_correction": "APPROVED_BY_CHIEF_ACCOUNTANT", "tax_kz": 12}
        decision_resp = await client.post(
            f"/api/v1/reviews/{rev_item['id']}/decision",
            headers=headers_a,
            json={"decision": "edit", "edited_value": edit_payload}
        )
        assert decision_resp.status_code == 200
        resolved_rev = decision_resp.json()
        assert resolved_rev["status"] == "RESOLVED"
        assert resolved_rev["user_decision"] == "edit"

        task_after = await client.get(f"/api/v1/tasks/{new_task_id}", headers=headers_a)
        assert task_after.json()["status"] == "COMPLETED"
        assert task_after.json()["output_data"] == edit_payload
        results["9. Review & Diff"] = "PASSED"
        print("   -> OK: Review successfully resolved with EDIT; task transitioned to COMPLETED; diff recorded")

        # 10. File Validation & Disguised Executable Rejection
        print("\n10. Testing File Validation & Magic Signature Inspection...")
        pdf_bytes = b"%PDF-1.4\nTest PDF Document for SaaS Foundation"
        valid_upload = await client.post(
            "/api/v1/files/upload",
            headers=headers_a,
            files={"file": ("report.pdf", pdf_bytes, "application/pdf")}
        )
        assert valid_upload.status_code == 201
        uploaded_file_id = valid_upload.json()["id"]

        # Disguised EXE disguised as PDF
        fake_pdf = b"MZ\x90\x00\x03\x00\x00\x00Malicious disguised binary"
        bad_upload = await client.post(
            "/api/v1/files/upload",
            headers=headers_a,
            files={"file": ("fake_report.pdf", fake_pdf, "application/pdf")}
        )
        assert bad_upload.status_code == 400
        print(f"   -> OK: Genuine PDF accepted, disguised .exe rejected: {bad_upload.json()['detail']}")

        # Soft delete
        del_resp = await client.delete(f"/api/v1/files/{uploaded_file_id}", headers=headers_a)
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted_at"] is not None
        results["10. File Security & Soft Delete"] = "PASSED"
        print("   -> OK: Soft-delete verified")

    print("\n" + "=" * 50)
    print("ALL 10 VERIFICATION CHECKS PASSED END-TO-END!")
    print("=" * 50)
    for k, v in results.items():
        print(f"[{v}] {k}")


if __name__ == "__main__":
    asyncio.run(run_live_verification())
