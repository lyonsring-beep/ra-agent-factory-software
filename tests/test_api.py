from fastapi.testclient import TestClient

from ra_agent_studio.api import app, studio
from tests.support import authority_registry


def test_health_and_command_only_module_flow() -> None:
    studio.authority = authority_registry()
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}

    # Legacy mutation endpoint is intentionally unavailable: B12 has one mutation plane.
    legacy = client.post(
        "/modules",
        headers={"Authorization": "Bearer builder-token"},
        json={"module_id": "api-m0", "revision_id": "api-r0", "name": "Denied", "content": "print('x')"},
    )
    assert legacy.status_code in {404, 405}

    unauthorized = client.post(
        "/commands",
        json={
            "command_id":"api-cmd-unauth",
            "operation_descriptor_id":"op:factory:module-revision-create",
            "exact_target_ref":"api-r0",
            "workspace_ref":"ws",
            "idempotency_key":"api-idem-unauth",
            "expected_recovery_epoch":studio.store.recovery_epoch(),
            "payload":{"module_id":"api-m0","name":"Denied","content":"print('x')"},
        },
    )
    assert unauthorized.status_code == 401

    response = client.post(
        "/commands",
        headers={"Authorization": "Bearer builder-token"},
        json={
            "command_id":"api-cmd-module-v103",
            "operation_descriptor_id":"op:factory:module-revision-create",
            "exact_target_ref":"api-r1-v103",
            "workspace_ref":"ws",
            "idempotency_key":"api-idem-module-v103",
            "expected_recovery_epoch":studio.store.recovery_epoch(),
            "payload":{
                "module_id":"api-m1-v103",
                "name":"API Module",
                "content":"import sys\nprint(sys.stdin.read())\n",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["standing"] in {"COMMITTED","REPLAYED"}
    listed = client.get("/modules")
    assert listed.status_code == 200
    assert any(item["revision_id"]["value"] == "api-r1-v103" for item in listed.json())
