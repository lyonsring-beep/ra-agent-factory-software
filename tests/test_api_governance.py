from fastapi.testclient import TestClient

from ra_agent_studio.api import app, studio
from tests.support import authority_registry


def test_legacy_review_endpoint_cannot_bypass_control_plane() -> None:
    studio.authority = authority_registry()
    client = TestClient(app)
    response = client.post(
        "/reviews",
        headers={"Authorization":"Bearer reviewer-token"},
        json={"candidate_id": "x", "review_method": "external_ai", "passed": True},
    )
    assert response.status_code in {404,405}


def test_command_endpoint_does_not_accept_caller_supplied_principal() -> None:
    studio.authority = authority_registry()
    client=TestClient(app)
    response=client.post(
        "/commands",
        headers={"Authorization":"Bearer builder-token"},
        json={
            "command_id":"principal-binding-v103",
            "operation_descriptor_id":"op:factory:module-revision-create",
            "exact_target_ref":"principal-r1",
            "workspace_ref":"ws",
            "idempotency_key":"principal-idem-v103",
            "expected_recovery_epoch":studio.store.recovery_epoch(),
            "payload":{
                "module_id":"principal-m1","name":"M","content":"print('x')",
                "principal_ref":"reviewer",
            },
        },
    )
    assert response.status_code == 200
    # The authenticated bearer principal owns the authoring action; payload cannot mint reviewer authority.
    module=studio.get_module("principal-r1")
    assert module.author_principal_id == "builder"


def test_snapshot_endpoint_exposes_authoritative_projection_and_audit() -> None:
    client = TestClient(app)
    response = client.get("/snapshot")
    assert response.status_code == 200
    assert set(response.json()) == {
        "modules",
        "compositions",
        "evidence",
        "candidates",
        "reviews",
        "freezes",
        "baselines",
        "deployments",
        "production_runs",
        "audit",
    }
